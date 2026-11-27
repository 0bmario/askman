// ort-sys 2.0.0-rc.9 links any libonnxruntime that pkg-config reports with minor version >= 20,
// dynamically and in place of the pinned static ONNX Runtime 1.20, so `cargo install askman` can
// build a binary that fails to start or runs another runtime. Stop such a build instead.
// This copies ort-sys rc.9's rule: delete this file once ort-sys no longer probes pkg-config by default.
use std::env;
use std::ffi::OsString;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    if env_var("LIBONNXRUNTIME_NO_PKG_CONFIG").is_some() {
        return;
    }
    let Some(version) = pkg_config_onnxruntime_version() else {
        return;
    };
    let ort_sys_would_link_it = version
        .split('.')
        .nth(1)
        .and_then(|minor| minor.parse::<u32>().ok())
        .is_some_and(|minor| minor >= 20);
    if ort_sys_would_link_it {
        panic!(
            "pkg-config found a system ONNX Runtime ({version}), which would replace askman's bundled one. \
             Set LIBONNXRUNTIME_NO_PKG_CONFIG=1 and rerun, or install with install.sh \
             (https://github.com/0bmario/askman#installation)."
        );
    }
}

/// The version pkg-config reports, found the way the `pkg-config` crate (used by ort-sys) runs it.
/// None whenever ort-sys's probe would fail, or when unsure.
fn pkg_config_onnxruntime_version() -> Option<String> {
    // Like the pkg-config crate, probe only for native builds; cross builds continue.
    if env::var_os("HOST") != env::var_os("TARGET") {
        return None;
    }
    let libs = run_pkg_config(&["--libs", "--cflags", "libonnxruntime"])?;
    if !libs.status.success() {
        return None;
    }
    let version = run_pkg_config(&["--modversion", "libonnxruntime"])?;
    if !version.status.success() {
        return None;
    }
    Some(String::from_utf8(version.stdout).ok()?.trim().to_string())
}

fn run_pkg_config(args: &[&str]) -> Option<std::process::Output> {
    // The pkg-config crate's `--static` switches; ort-sys sets none of its own.
    let is_static = env_var("LIBONNXRUNTIME_STATIC").is_some()
        || (env_var("LIBONNXRUNTIME_DYNAMIC").is_none() && env_var("PKG_CONFIG_ALL_STATIC").is_some());
    let command = |program: OsString| {
        let mut command = Command::new(program);
        if is_static {
            command.arg("--static");
        }
        command.args(args);
        for name in ["PKG_CONFIG_PATH", "PKG_CONFIG_LIBDIR", "PKG_CONFIG_SYSROOT_DIR"] {
            if let Some(value) = host_env_var(name) {
                command.env(name, value);
            }
        }
        command.output().ok()
    };
    match host_env_var("PKG_CONFIG") {
        Some(program) => command(program),
        None => command("pkg-config".into()).or_else(|| command("pkgconf".into())),
    }
}

/// `<NAME>_<target>`, `<NAME>_<target with _>`, `HOST_<NAME>`, then `<NAME>`, as the pkg-config crate
/// reads its variables for a native build.
fn host_env_var(name: &str) -> Option<OsString> {
    let target = env::var("TARGET").unwrap_or_default();
    [
        format!("{name}_{target}"),
        format!("{name}_{}", target.replace('-', "_")),
        format!("HOST_{name}"),
        name.to_string(),
    ]
    .into_iter()
    .find_map(|candidate| env_var(&candidate))
}

fn env_var(name: &str) -> Option<OsString> {
    println!("cargo:rerun-if-env-changed={name}");
    env::var_os(name)
}
