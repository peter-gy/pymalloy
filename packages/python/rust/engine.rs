use deno_core::{Extension, JsRuntime, RuntimeOptions, op2, v8};
use std::{
    borrow::Cow,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

use crate::worker::{Control, Error, MAX_BYTES, Owner};

#[op2(fast)]
fn op_pymalloy_random(#[buffer] bytes: &mut [u8]) -> Result<(), deno_error::JsErrorBox> {
    getrandom::fill(bytes).map_err(|error| deno_error::JsErrorBox::generic(error.to_string()))
}

deno_core::extension!(pymalloy_host, ops = [op_pymalloy_random]);

mod bundled_runtime {
    include!(concat!(env!("OUT_DIR"), "/runtime_sources.rs"));
}

fn bundled_extension(mut extension: Extension) -> Result<Extension, Error> {
    // Upstream descriptors identify files in the builder's Cargo registry.
    // Resolve every source through the wheel's compile-time source table.
    for files in [
        &mut extension.js_files,
        &mut extension.esm_files,
        &mut extension.lazy_loaded_js_files,
        &mut extension.lazy_loaded_esm_files,
    ] {
        let sources = files
            .iter()
            .map(|file| {
                bundled_runtime::SOURCES
                    .iter()
                    .find(|source| source.specifier == file.specifier)
                    .cloned()
                    .ok_or_else(|| {
                        Error::Runtime(format!(
                            "Bundled runtime source is unavailable: {}",
                            file.specifier
                        ))
                    })
            })
            .collect::<Result<Vec<_>, _>>()?;
        *files = Cow::Owned(sources);
    }
    Ok(extension)
}

pub struct Engine {
    runtime: JsRuntime,
    exhausted: Arc<AtomicBool>,
    _tokio: tokio::runtime::Runtime,
}

impl Engine {
    pub fn new(owner: &Arc<Owner>, generation: u64) -> Result<Self, Error> {
        // V8 must finish creating the isolate before its heap callback can be
        // installed. Reject budgets that cannot safely hold that bootstrap.
        if owner.memory_bytes < 16 * 1024 * 1024 {
            return Err(Error::Memory);
        }
        let tokio = tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .map_err(|error| Error::Runtime(error.to_string()))?;
        let _guard = tokio.enter();
        let mut runtime = JsRuntime::try_new(RuntimeOptions {
            extensions: vec![
                bundled_extension(deno_webidl::deno_webidl::init())?,
                bundled_extension(deno_web::deno_web::init(
                    Arc::new(deno_web::BlobStore::default()),
                    None,
                    false,
                    Default::default(),
                ))?,
                pymalloy_host::init(),
            ],
            create_params: Some(v8::Isolate::create_params().heap_limits(0, owner.memory_bytes)),
            ..Default::default()
        })
        .map_err(|error| Error::Runtime(error.to_string()))?;
        let handle = runtime.v8_isolate().thread_safe_handle();
        let exhausted = Arc::new(AtomicBool::new(false));
        let exhausted_callback = exhausted.clone();
        let heap_handle = handle.clone();
        runtime.add_near_heap_limit_callback(move |current, _initial| {
            exhausted_callback.store(true, Ordering::Release);
            heap_handle.terminate_execution();
            // Termination still needs allocation headroom to unwind JavaScript
            // and destroy this isolate on its owning thread.
            current.saturating_add(64 * 1024 * 1024)
        });
        *owner.control.lock()? = Some(Control { generation, handle });
        let mut engine = Self {
            runtime,
            exhausted,
            _tokio: tokio,
        };
        if owner.stopping.load(Ordering::Acquire) {
            return Err(Error::Closed);
        }
        engine.evaluate("pymalloy:bootstrap", include_str!("bootstrap.js"))?;
        engine.evaluate(
            "pymalloy:compiler",
            include_str!("../src/pymalloy/_assets/compiler.js"),
        )?;
        Ok(engine)
    }

    fn evaluate(&mut self, name: &'static str, source: &'static str) -> Result<(), Error> {
        let _guard = self._tokio.enter();
        let result = self.runtime.execute_script(name, source);
        if self.exhausted.load(Ordering::Acquire) {
            return Err(Error::Memory);
        }
        result
            .map(|_| ())
            .map_err(|error| Error::Runtime(error.to_string()))
    }

    pub fn handle(&mut self) -> v8::IsolateHandle {
        self.runtime.v8_isolate().thread_safe_handle()
    }

    pub fn advance(&mut self, start: bool, input: &[u8]) -> Result<Vec<u8>, Error> {
        let _guard = self._tokio.enter();
        deno_core::scope!(scope, self.runtime);
        v8::tc_scope!(let scope, scope);
        let context = scope.get_current_context();
        let key = v8::String::new(scope, "__pymalloy").ok_or(Error::Memory)?;
        let api = context
            .global(scope)
            .get(scope, key.into())
            .and_then(|value| value.to_object(scope))
            .ok_or_else(|| Error::Runtime("Compiler entrypoint is unavailable".into()))?;
        let key =
            v8::String::new(scope, if start { "start" } else { "step" }).ok_or(Error::Memory)?;
        let function = api
            .get(scope, key.into())
            .and_then(|value| v8::Local::<v8::Function>::try_from(value).ok())
            .ok_or_else(|| Error::Runtime("Compiler method is unavailable".into()))?;
        let input = std::str::from_utf8(input)
            .map_err(|_| Error::Invalid("Compiler input must be UTF-8 JSON".into()))?;
        let argument = v8::String::new(scope, input).ok_or(Error::Memory)?;
        let value = function.call(scope, api.into(), &[argument.into()]);
        if self.exhausted.load(Ordering::Acquire) {
            return Err(Error::Memory);
        }
        let value = value.ok_or_else(|| {
            if scope.is_execution_terminating() {
                Error::Closed
            } else {
                Error::Runtime(
                    scope
                        .exception()
                        .map(|error| error.to_rust_string_lossy(scope))
                        .unwrap_or_else(|| "JavaScript compiler failed".into()),
                )
            }
        })?;
        let value = v8::Local::<v8::String>::try_from(value)
            .map_err(|_| Error::Runtime("Compiler returned a non-string response".into()))?;
        if value.utf8_length(scope) > MAX_BYTES {
            return Err(Error::Limit);
        }
        Ok(value.to_rust_string_lossy(scope).into_bytes())
    }
}
