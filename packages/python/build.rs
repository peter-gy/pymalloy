use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, error::Error, fs, io::Write, path::Path};

fn required(path: &Path) -> Result<Vec<u8>, Box<dyn Error>> {
    writeln!(
        std::io::stdout(),
        "cargo:rerun-if-changed={}",
        path.display()
    )?;
    let bytes = fs::read(path).map_err(|error| {
        format!(
            "Missing PyMalloy asset {}: {error}. Run pnpm build before building Python.",
            path.display()
        )
    })?;
    if bytes.is_empty() {
        return Err(format!("Empty PyMalloy asset {}", path.display()).into());
    }
    Ok(bytes)
}

fn check_digest(
    manifest: &serde_json::Value,
    field: &str,
    path: &Path,
) -> Result<(), Box<dyn Error>> {
    let digest = Sha256::digest(required(path)?)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    if manifest[field].as_str() != Some(digest.as_str()) {
        return Err(format!("Asset digest mismatch for {}: {field}", path.display()).into());
    }
    Ok(())
}

fn pinned_dependency<'a>(cargo: &'a toml::Value, name: &str) -> Result<&'a str, Box<dyn Error>> {
    cargo
        .get("dependencies")
        .and_then(|dependencies| dependencies.get(name))
        .and_then(|requirement| {
            requirement
                .as_str()
                .or_else(|| requirement.get("version").and_then(toml::Value::as_str))
        })
        .and_then(|version| version.strip_prefix('='))
        .ok_or_else(|| format!("Engine dependency must pin an exact version: {name}").into())
}

fn embed_runtime_sources(assets: &Path, cargo: &toml::Value) -> Result<(), Box<dyn Error>> {
    let runtime: serde_json::Value =
        serde_json::from_slice(&required(&assets.join("native.runtime.json"))?)?;
    let packages = runtime["packages"]
        .as_array()
        .ok_or("Native runtime manifest must list packages")?;
    let mut names = BTreeSet::new();
    let mut sources = Vec::new();
    for package in packages {
        let name = package["name"]
            .as_str()
            .ok_or("Missing native runtime package name")?;
        if !matches!(name, "deno_web" | "deno_webidl") || !names.insert(name) {
            return Err(format!("Unexpected native runtime package: {name}").into());
        }
        if package["version"].as_str() != Some(pinned_dependency(cargo, name)?) {
            return Err(format!("Native runtime package version mismatch: {name}").into());
        }
        let files = package["sources"]
            .as_object()
            .ok_or("Native runtime package must list sources")?;
        if files.is_empty() {
            return Err(format!("Native runtime package has no sources: {name}").into());
        }
        let prefix = format!("ext:{name}/");
        for (specifier, source) in files {
            let filename = specifier
                .strip_prefix(&prefix)
                .ok_or("Invalid runtime source specifier")?;
            if filename.contains('/') || !(filename.ends_with(".js") || filename.ends_with(".mjs"))
            {
                return Err(format!("Invalid native runtime source specifier: {specifier}").into());
            }
            let source = source
                .as_str()
                .ok_or("Native runtime source must contain JavaScript text")?;
            if !source.is_ascii() {
                return Err(format!("Native runtime source must be ASCII: {specifier}").into());
            }
            sources.push((specifier, source));
        }
    }
    if names.len() != 2 {
        return Err("Native runtime manifest must include deno_web and deno_webidl".into());
    }
    sources.sort_unstable_by_key(|(specifier, _)| *specifier);
    let entries = sources.into_iter().map(|(specifier, source)| {
        format!("deno_core::ExtensionFileSource::new({specifier:?}, deno_core::ascii_str!({source:?}))")
    }).collect::<Vec<_>>().join(",\n");
    let generated =
        format!("pub const SOURCES: &[deno_core::ExtensionFileSource] = &[\n{entries}\n];\n");
    fs::write(
        Path::new(&std::env::var("OUT_DIR")?).join("runtime_sources.rs"),
        generated,
    )?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let assets = Path::new("src/pymalloy/_assets");
    let native_manifest: serde_json::Value =
        serde_json::from_slice(&required(&assets.join("native.manifest.json"))?)
            .map_err(|error| format!("Invalid native dependency manifest: {error}"))?;
    for (field, path) in [
        ("cargoLockSha256", Path::new("Cargo.lock").to_path_buf()),
        ("runtimeSha256", assets.join("native.runtime.json")),
    ] {
        check_digest(&native_manifest, field, &path)?;
    }
    for name in [
        "widget/index.js",
        "widget/widget.css",
        "agent/plugin.json",
        "agent/skills/pymalloy/SKILL.md",
    ] {
        required(&assets.join(name))?;
    }
    let widget: serde_json::Value =
        serde_json::from_slice(&required(&assets.join("widget/anywidget.json"))?)
            .map_err(|error| format!("Invalid widget asset manifest: {error}"))?;
    for module in widget["modules"]
        .as_array()
        .ok_or("Widget manifest must list modules")?
    {
        let name = module.as_str().ok_or("Widget module must be a filename")?;
        if name.contains("..") || Path::new(name).is_absolute() {
            return Err("Invalid widget module path".into());
        }
        required(&assets.join("widget").join(name))?;
    }
    let manifest_bytes = required(&assets.join("compiler.manifest.json"))?;
    let manifest: serde_json::Value = serde_json::from_slice(&manifest_bytes)
        .map_err(|error| format!("Invalid compiler manifest: {error}"))?;
    check_digest(&manifest, "bundleSha256", &assets.join("compiler.js"))?;
    for (field, file) in [
        ("protocolSha256", "compiler.protocol.json"),
        ("patchSha256", "compiler.malloy.patch"),
    ] {
        check_digest(&manifest, field, &assets.join(file))?;
    }
    if manifest["malloyVersion"].as_str().is_none_or(str::is_empty) {
        return Err("Missing Malloy compiler version".into());
    }
    let cargo: toml::Value = toml::from_str(&fs::read_to_string("Cargo.toml")?)
        .map_err(|error| format!("Invalid Cargo manifest: {error}"))?;
    let bootstrap = cargo
        .get("package")
        .and_then(|package| package.get("metadata"))
        .and_then(|metadata| metadata.get("pymalloy"))
        .and_then(|pymalloy| pymalloy.get("bootstrap-revision"))
        .and_then(toml::Value::as_integer)
        .ok_or("Missing compiler bootstrap revision in Cargo manifest")?;
    if manifest["bootstrapRevision"].as_i64() != Some(bootstrap) {
        return Err("Compiler bootstrap revision mismatch".into());
    }
    for (field, dependency) in [
        ("denoCore", "deno_core"),
        ("denoWeb", "deno_web"),
        ("denoWebidl", "deno_webidl"),
    ] {
        let version = pinned_dependency(&cargo, dependency)?;
        if manifest["engine"][field].as_str() != Some(version) {
            return Err(format!("Compiler engine dependency mismatch: {field}").into());
        }
    }
    embed_runtime_sources(assets, &cargo)?;
    writeln!(std::io::stdout(), "cargo:rerun-if-changed=Cargo.toml")?;
    if std::env::var("PROFILE")?.as_str() == "release"
        && std::env::var("CARGO_CFG_TARGET_OS")?.as_str() == "macos"
    {
        writeln!(std::io::stdout(), "cargo:rustc-link-arg-cdylib=-Wl,-S")?;
    }
    pyo3_build_config::add_extension_module_link_args();
    Ok(())
}
