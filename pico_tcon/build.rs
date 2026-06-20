//! Build script: runs on your PC at compile time, before the firmware is built.
//! It hands our memory map (memory.x) to the linker and adds the linker scripts
//! that cortex-m-rt and embassy-rp provide.

use std::env;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn main() {
    // Copy memory.x into the build output dir and add that dir to the linker's
    // search path, so the linker can find our chip memory map.
    let out = &PathBuf::from(env::var_os("OUT_DIR").unwrap());
    File::create(out.join("memory.x"))
        .unwrap()
        .write_all(include_bytes!("memory.x"))
        .unwrap();
    println!("cargo:rustc-link-search={}", out.display());

    // Rebuild if the memory map changes.
    println!("cargo:rerun-if-changed=memory.x");

    // Linker arguments:
    //   --nmagic     : don't page-align sections (saves flash)
    //   -Tlink.x     : the cortex-m-rt linker script (vector table, startup)
    //   -Tlink-rp.x  : embassy-rp's script (places the boot2 bootloader)
    println!("cargo:rustc-link-arg-bins=--nmagic");
    println!("cargo:rustc-link-arg-bins=-Tlink.x");
    println!("cargo:rustc-link-arg-bins=-Tlink-rp.x");
}
