mod engine;
mod worker;

use pyo3::{
    exceptions::{PyMemoryError, PyRuntimeError, PyTimeoutError, PyValueError},
    prelude::*,
    types::PyBytes,
};
use serde::Deserialize;
use std::{
    sync::{Arc, Mutex, atomic::Ordering, mpsc},
    time::{Duration, Instant},
};
use worker::{CLOSE_LIMIT, Command, Error, MAX_BYTES, Owner, POLL, process_check};

impl From<Error> for PyErr {
    fn from(error: Error) -> Self {
        match error {
            Error::Closed => PyRuntimeError::new_err("Compiler is closed"),
            Error::Fork => PyRuntimeError::new_err(
                "Embedded compiler cannot be used after fork. Start a fresh process with spawn.",
            ),
            Error::Invalid(message) => PyValueError::new_err(message),
            Error::Runtime(message) => PyRuntimeError::new_err(message),
            Error::Limit => PyRuntimeError::new_err("Compiler message exceeds the 64 MiB limit"),
            Error::Memory => {
                PyMemoryError::new_err("Compiler exceeded its managed heap memory budget")
            }
            Error::Timeout => PyTimeoutError::new_err("Compiler operation timed out"),
            Error::QueueFull => PyRuntimeError::new_err("Compiler startup queue is full"),
        }
    }
}

fn bytes(value: &Bound<'_, PyBytes>) -> PyResult<Vec<u8>> {
    let value = value.as_bytes();
    if value.len() > MAX_BYTES {
        return Err(Error::Limit.into());
    }
    if std::str::from_utf8(value).is_err() {
        return Err(Error::Invalid("Compiler input must be UTF-8 JSON".into()).into());
    }
    Ok(value.to_vec())
}

fn settle(py: Python<'_>, owner: &Arc<Owner>) -> PyResult<()> {
    owner.cancel(None)?;
    let Some(worker) = owner.worker()? else {
        return Ok(());
    };
    let deadline = Instant::now() + CLOSE_LIMIT;
    let mut signal = None;
    loop {
        if py.detach(|| worker.poll_finished(POLL))? {
            break;
        }
        if signal.is_none() {
            signal = py.check_signals().err();
        }
        if Instant::now() >= deadline {
            return Err(signal.unwrap_or_else(|| {
                PyRuntimeError::new_err("Compiler teardown exceeded five seconds")
            }));
        }
    }
    py.detach(|| worker.join())?;
    if let Some(signal) = signal {
        return Err(signal);
    }
    Ok(())
}

#[pyclass(module = "pymalloy._native")]
struct Compiler {
    owner: Arc<Owner>,
}

#[pymethods]
impl Compiler {
    #[new]
    #[pyo3(signature = (memory_mb = 1024))]
    fn new(memory_mb: usize) -> PyResult<Self> {
        process_check()?;
        if memory_mb == 0 {
            return Err(PyValueError::new_err("memory_mb must be positive"));
        }
        let memory_bytes = memory_mb
            .checked_mul(1024 * 1024)
            .ok_or_else(|| PyValueError::new_err("memory_mb is too large"))?;
        Ok(Self {
            owner: Owner::new(memory_bytes),
        })
    }

    fn start(&self, request: &Bound<'_, PyBytes>) -> PyResult<Job> {
        process_check()?;
        let request = bytes(request)?;
        let generation = self.owner.reserve()?;
        Ok(Job {
            owner: self.owner.clone(),
            generation,
            state: Mutex::new(JobState::Ready(request)),
        })
    }

    #[getter]
    fn closed(&self) -> PyResult<bool> {
        process_check()?;
        Ok(self.owner.stopping.load(Ordering::Acquire))
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        settle(py, &self.owner)
    }
}

impl Drop for Compiler {
    fn drop(&mut self) {
        let _ = self.owner.cancel(None);
    }
}

enum JobState {
    Ready(Vec<u8>),
    Waiting,
    Busy,
    Done,
    Closed,
}

#[pyclass(module = "pymalloy._native")]
struct Job {
    owner: Arc<Owner>,
    generation: u64,
    state: Mutex<JobState>,
}

#[derive(Deserialize)]
struct Header<'a> {
    #[serde(borrow)]
    kind: &'a str,
}

#[pymethods]
impl Job {
    #[pyo3(signature = (answers = None, timeout = 30.0))]
    fn step<'py>(
        &self,
        py: Python<'py>,
        answers: Option<&Bound<'_, PyBytes>>,
        timeout: f64,
    ) -> PyResult<Bound<'py, PyBytes>> {
        process_check()?;
        if !timeout.is_finite() || timeout < 0.0 {
            return Err(PyValueError::new_err(
                "timeout must be finite and nonnegative",
            ));
        }
        let duration = Duration::try_from_secs_f64(timeout)
            .map_err(|_| PyValueError::new_err("timeout is too large"))?;
        let deadline = Instant::now()
            .checked_add(duration)
            .ok_or_else(|| PyValueError::new_err("timeout is too large"))?;
        let answers = answers.map(bytes).transpose()?;
        let (start, input) = {
            let mut state = self.state.lock().map_err(Error::from)?;
            if self.owner.stopping.load(Ordering::Acquire) {
                return Err(Error::Closed.into());
            }
            match &*state {
                JobState::Ready(_) if answers.is_some() => {
                    return Err(PyValueError::new_err(
                        "The first job step requires answers=None",
                    ));
                }
                JobState::Waiting if answers.is_none() => {
                    return Err(PyValueError::new_err(
                        "A pending job step requires host answers",
                    ));
                }
                JobState::Busy => {
                    return Err(PyRuntimeError::new_err("Job already has a running step"));
                }
                JobState::Done | JobState::Closed => {
                    return Err(PyRuntimeError::new_err("Job is closed"));
                }
                _ => {}
            }
            match std::mem::replace(&mut *state, JobState::Busy) {
                JobState::Ready(request) => (true, request),
                JobState::Waiting => (
                    false,
                    answers.ok_or_else(|| {
                        PyValueError::new_err("A pending job step requires host answers")
                    })?,
                ),
                _ => return Err(PyRuntimeError::new_err("Job state changed during its step")),
            }
        };
        let result = (|| -> PyResult<Vec<u8>> {
            py.check_signals()?;
            if Instant::now() >= deadline {
                return Err(Error::Timeout.into());
            }
            let worker = loop {
                match py.detach(|| self.owner.start_worker()) {
                    Ok(worker) => break worker,
                    Err(Error::QueueFull) => {
                        py.check_signals()?;
                        let remaining = deadline.saturating_duration_since(Instant::now());
                        if remaining.is_zero() {
                            return Err(Error::Timeout.into());
                        }
                        py.detach(|| std::thread::sleep(POLL.min(remaining)));
                    }
                    Err(error) => return Err(error.into()),
                }
            };
            let (reply, mut receive) = mpsc::sync_channel(1);
            worker.submit(Command {
                generation: self.generation,
                start,
                input,
                reply,
            })?;
            loop {
                let remaining = deadline.saturating_duration_since(Instant::now());
                let receive_ref = &mut receive;
                match py.detach(move || receive_ref.recv_timeout(POLL.min(remaining))) {
                    Ok(response) => return Ok(response?),
                    Err(mpsc::RecvTimeoutError::Disconnected) => {
                        return Err(PyRuntimeError::new_err(
                            "Compiler thread exited before completing its step",
                        ));
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                }
                py.check_signals()?;
                if self.owner.stopping.load(Ordering::Acquire) {
                    return Err(Error::Closed.into());
                }
                if Instant::now() >= deadline {
                    return Err(Error::Timeout.into());
                }
            }
        })();
        let result = result.and_then(|response| {
            let header: Header<'_> = serde_json::from_slice(&response)
                .map_err(|_| PyRuntimeError::new_err("Compiler returned invalid response JSON"))?;
            *self.state.lock().map_err(Error::from)? = if header.kind == "needs" {
                JobState::Waiting
            } else {
                JobState::Done
            };
            if header.kind != "needs" {
                self.owner.finish(self.generation)?;
            }
            Ok(PyBytes::new(py, &response))
        });
        if result.is_err() {
            if let Ok(mut state) = self.state.lock() {
                *state = JobState::Closed;
            }
            let _ = self.owner.cancel(Some(self.generation));
            let _ = settle(py, &self.owner);
        }
        result
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        process_check()?;
        let completed = {
            let mut state = self.state.lock().map_err(Error::from)?;
            let completed = matches!(*state, JobState::Done);
            if !completed {
                *state = JobState::Closed;
            }
            completed
        };
        if completed {
            return Ok(());
        }
        settle(py, &self.owner)
    }
}

impl Drop for Job {
    fn drop(&mut self) {
        if process_check().is_err() {
            return;
        }
        let state = self
            .state
            .get_mut()
            .unwrap_or_else(|error| error.into_inner());
        if !matches!(state, JobState::Done | JobState::Closed) {
            let _ = self.owner.cancel(Some(self.generation));
        }
    }
}

#[pyfunction]
fn _abandon_inherited(value: Py<PyAny>, creator_pid: u32) -> PyResult<()> {
    if creator_pid == 0 || creator_pid == std::process::id() {
        return Err(PyValueError::new_err(
            "Inherited resource abandonment requires a different creator process",
        ));
    }
    // A native object's destructor can lock threads lost across fork. Retain an
    // owned Python reference until the child process exits through the OS.
    std::mem::forget(value);
    Ok(())
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<Compiler>()?;
    module.add_class::<Job>()?;
    module.add_function(wrap_pyfunction!(_abandon_inherited, module)?)?;
    module.add(
        "MANIFEST",
        include_str!("../src/pymalloy/_assets/compiler.manifest.json"),
    )?;
    Ok(())
}
