use deno_core::{JsRuntime, v8};
use std::{
    sync::{
        Arc, Condvar, Mutex, OnceLock, PoisonError,
        atomic::{AtomicBool, AtomicU32, Ordering},
        mpsc::{self, Receiver, SyncSender},
    },
    thread::{self, JoinHandle},
    time::Duration,
};

use crate::engine::Engine;

pub const MAX_BYTES: usize = 64 * 1024 * 1024;
pub const POLL: Duration = Duration::from_millis(10);
pub const CLOSE_LIMIT: Duration = Duration::from_secs(5);
static PROCESS: AtomicU32 = AtomicU32::new(0);
static PLATFORM: OnceLock<Result<SyncSender<Spawn>, String>> = OnceLock::new();

#[derive(Debug)]
pub enum Error {
    Closed,
    Fork,
    Invalid(String),
    Runtime(String),
    Limit,
    Memory,
    Timeout,
    QueueFull,
}

impl<T> From<PoisonError<T>> for Error {
    fn from(_: PoisonError<T>) -> Self {
        Self::Runtime("Compiler state lock is poisoned".into())
    }
}

pub fn process_check() -> Result<(), Error> {
    let pid = std::process::id();
    let initial = PROCESS.load(Ordering::Acquire);
    if initial == pid {
        return Ok(());
    }
    if initial != 0 {
        return Err(Error::Fork);
    }
    match PROCESS.compare_exchange(0, pid, Ordering::AcqRel, Ordering::Acquire) {
        Ok(_) => Ok(()),
        Err(previous) if previous == pid => Ok(()),
        Err(_) => Err(Error::Fork),
    }
}

pub struct Control {
    pub generation: u64,
    pub handle: v8::IsolateHandle,
}

pub struct Owner {
    pub memory_bytes: usize,
    pub stopping: AtomicBool,
    pub control: Mutex<Option<Control>>,
    state: Mutex<State>,
}

struct State {
    active: Option<u64>,
    next: u64,
    worker: Option<Arc<Worker>>,
}

pub struct Worker {
    tx: SyncSender<Command>,
    done: Arc<(Mutex<bool>, Condvar)>,
    join: Mutex<Option<JoinHandle<()>>>,
}

struct Spawn {
    owner: Arc<Owner>,
    commands: Receiver<Command>,
    worker: Arc<Worker>,
}

pub struct Command {
    pub generation: u64,
    pub start: bool,
    pub input: Vec<u8>,
    pub reply: SyncSender<Result<Vec<u8>, Error>>,
}

fn platform() -> Result<&'static SyncSender<Spawn>, Error> {
    PLATFORM
        .get_or_init(|| {
            let (tx, rx) = mpsc::sync_channel::<Spawn>(32);
            thread::Builder::new()
                .name("pymalloy-v8-platform".into())
                .spawn(move || {
                    // Every isolate thread descends from the platform owner. The
                    // unprotected platform permits initialization off the main thread
                    // on Linux CPUs with protection keys enabled.
                    JsRuntime::init_platform(Some(
                        v8::new_unprotected_default_platform(0, false).make_shared(),
                    ));
                    for spawn in rx {
                        let Spawn {
                            owner,
                            commands,
                            worker,
                        } = spawn;
                        let done = worker.done.clone();
                        let owner_on_failure = owner.clone();
                        let handle = thread::Builder::new()
                            .name("pymalloy-compiler".into())
                            .stack_size(8 * 1024 * 1024)
                            .spawn(move || {
                                let _ =
                                    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                                        run(&owner, commands)
                                    }));
                                *owner
                                    .control
                                    .lock()
                                    .unwrap_or_else(|error| error.into_inner()) = None;
                                owner.stopping.store(true, Ordering::Release);
                                let (lock, condition) = &*done;
                                *lock.lock().unwrap_or_else(|error| error.into_inner()) = true;
                                condition.notify_all();
                            });
                        match handle {
                            Ok(handle) => {
                                *worker
                                    .join
                                    .lock()
                                    .unwrap_or_else(|error| error.into_inner()) = Some(handle);
                            }
                            Err(_) => {
                                owner_on_failure.stopping.store(true, Ordering::Release);
                                let (lock, condition) = &*worker.done;
                                *lock.lock().unwrap_or_else(|error| error.into_inner()) = true;
                                condition.notify_all();
                            }
                        }
                    }
                })
                .map(|_| tx)
                .map_err(|error| error.to_string())
        })
        .as_ref()
        .map_err(|error| Error::Runtime(format!("Could not create V8 platform thread: {error}")))
}

fn run(owner: &Arc<Owner>, commands: Receiver<Command>) {
    let mut engine: Option<Engine> = None;
    while !owner.stopping.load(Ordering::Acquire) {
        let command = match commands.recv_timeout(POLL) {
            Ok(command) => command,
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        };
        if owner.stopping.load(Ordering::Acquire) {
            break;
        }
        let result = (|| {
            if engine.is_none() {
                engine = Some(Engine::new(owner, command.generation)?);
            }
            let engine = engine
                .as_mut()
                .ok_or_else(|| Error::Runtime("Compiler engine failed to initialize".into()))?;
            *owner.control.lock()? = Some(Control {
                generation: command.generation,
                handle: engine.handle(),
            });
            if owner.stopping.load(Ordering::Acquire) {
                return Err(Error::Closed);
            }
            engine.advance(command.start, &command.input)
        })();
        *owner
            .control
            .lock()
            .unwrap_or_else(|error| error.into_inner()) = None;
        let failed = result.is_err();
        let _ = command.reply.send(result);
        if failed {
            owner.stopping.store(true, Ordering::Release);
        }
    }
    drop(engine);
}

impl Owner {
    pub fn new(memory_bytes: usize) -> Arc<Self> {
        Arc::new(Self {
            memory_bytes,
            stopping: AtomicBool::new(false),
            control: Mutex::new(None),
            state: Mutex::new(State {
                active: None,
                next: 1,
                worker: None,
            }),
        })
    }

    pub fn reserve(&self) -> Result<u64, Error> {
        process_check()?;
        let mut state = self.state.lock()?;
        if self.stopping.load(Ordering::Acquire) {
            return Err(Error::Closed);
        }
        if state.active.is_some() {
            return Err(Error::Invalid("Compiler already owns an active job".into()));
        }
        let id = state.next;
        state.next = state
            .next
            .checked_add(1)
            .ok_or_else(|| Error::Runtime("Compiler generation exhausted".into()))?;
        state.active = Some(id);
        Ok(id)
    }

    pub fn finish(&self, generation: u64) -> Result<(), Error> {
        let mut state = self.state.lock()?;
        if state.active == Some(generation) {
            state.active = None;
        }
        Ok(())
    }

    pub fn start_worker(self: &Arc<Self>) -> Result<Arc<Worker>, Error> {
        process_check()?;
        let mut state = self.state.lock()?;
        if self.stopping.load(Ordering::Acquire) {
            return Err(Error::Closed);
        }
        if let Some(worker) = &state.worker {
            return Ok(worker.clone());
        }
        let (tx, commands) = mpsc::sync_channel(1);
        let done = Arc::new((Mutex::new(false), Condvar::new()));
        let worker = Arc::new(Worker {
            tx,
            done: done.clone(),
            join: Mutex::new(None),
        });
        let spawn = Spawn {
            owner: self.clone(),
            commands,
            worker: worker.clone(),
        };
        match platform()?.try_send(spawn) {
            Ok(()) => state.worker = Some(worker.clone()),
            Err(mpsc::TrySendError::Full(_)) => return Err(Error::QueueFull),
            Err(mpsc::TrySendError::Disconnected(_)) => {
                return Err(Error::Runtime("V8 platform owner exited".into()));
            }
        }
        Ok(worker)
    }

    pub fn cancel(&self, generation: Option<u64>) -> Result<(), Error> {
        process_check()?;
        self.stopping.store(true, Ordering::Release);
        let control = self.control.lock()?;
        if let Some(control) = control.as_ref()
            && generation.is_none_or(|generation| generation == control.generation)
        {
            control.handle.terminate_execution();
        }
        Ok(())
    }

    pub fn worker(&self) -> Result<Option<Arc<Worker>>, Error> {
        Ok(self.state.lock()?.worker.clone())
    }
}

impl Worker {
    pub fn submit(&self, command: Command) -> Result<(), Error> {
        self.tx.try_send(command).map_err(|error| match error {
            mpsc::TrySendError::Full(_) => {
                Error::Invalid("Compiler already has a pending step".into())
            }
            mpsc::TrySendError::Disconnected(_) => Error::Closed,
        })
    }

    pub fn poll_finished(&self, duration: Duration) -> Result<bool, Error> {
        let (lock, condition) = &*self.done;
        let done = lock.lock()?;
        if *done {
            return Ok(true);
        }
        Ok(*condition.wait_timeout(done, duration)?.0)
    }

    pub fn join(&self) -> Result<(), Error> {
        if let Some(join) = self.join.lock()?.take() {
            join.join()
                .map_err(|_| Error::Runtime("Compiler thread panicked".into()))?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{Error, Owner};

    #[test]
    fn stale_completion_keeps_the_current_generation_reserved() -> Result<(), Error> {
        let owner = Owner::new(32 * 1024 * 1024);
        let first = owner.reserve()?;
        owner.finish(first)?;
        let second = owner.reserve()?;

        owner.finish(first)?;
        assert!(matches!(owner.reserve(), Err(Error::Invalid(_))));

        owner.finish(second)?;
        assert!(owner.reserve().is_ok());
        Ok(())
    }

    #[test]
    fn cancellation_rejects_later_reservations() -> Result<(), Error> {
        let owner = Owner::new(32 * 1024 * 1024);
        let generation = owner.reserve()?;

        owner.cancel(Some(generation))?;
        owner.finish(generation)?;

        assert!(matches!(owner.reserve(), Err(Error::Closed)));
        Ok(())
    }
}
