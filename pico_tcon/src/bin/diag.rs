#![no_std]
#![no_main]

// Combined Board Diagnostic Firmware:
//   1. Drives all 6 timing output pins (GP5, GP6, GP7, GP8, GP10, GP11) as fast square waves (measure ~1.65V DC).
//   2. Monitors the 4 inputs from the Pi and blinks the Pico LED:
//        * Solid ON: All 4 inputs are active.
//        * 1 blink & pause: PCLK (GP2) missing.
//        * 2 blinks & pause: DE (GP3) missing.
//        * 3 blinks & pause: HSYNC (GP4) missing.
//        * 4 blinks & pause: VSYNC (GP9) missing.

use embassy_executor::Spawner;
use embassy_rp::gpio::{Input, Level, Output, Pull};

#[ embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    let mut led = Output::new(p.PIN_25, Level::Low);

    // Outputs to drive:
    let mut soe = Output::new(p.PIN_5, Level::Low);   // SOE  -> GP5 (pin 7)
    let mut sspl = Output::new(p.PIN_6, Level::Low);  // SSPL -> GP6 (pin 9)
    let mut pol = Output::new(p.PIN_7, Level::Low);   // POL  -> GP7 (pin 10)
    let mut goe = Output::new(p.PIN_8, Level::Low);   // GOE  -> GP8 (pin 11)
    let mut gspu = Output::new(p.PIN_10, Level::Low); // GSPU -> GP10 (pin 14)
    let mut gsc = Output::new(p.PIN_11, Level::Low);  // GSC  -> GP11 (pin 15)

    // Inputs to monitor:
    let pclk = Input::new(p.PIN_2, Pull::None);   // PCLK -> GP2 (pin 4)
    let de = Input::new(p.PIN_3, Pull::None);     // DE   -> GP3 (pin 5)
    let hsync = Input::new(p.PIN_4, Pull::None);  // HSYNC-> GP4 (pin 6)
    let vsync = Input::new(p.PIN_9, Pull::None);  // VSYNC-> GP9 (pin 12)

    let mut i: u32 = 0;
    let mut out_high = false;

    loop {
        let mut pclk_toggled = false;
        let mut de_toggled = false;
        let mut hsync_toggled = false;
        let mut vsync_toggled = false;

        let mut last_pclk = pclk.is_high();
        let mut last_de = de.is_high();
        let mut last_hsync = hsync.is_high();
        let mut last_vsync = vsync.is_high();

        // Sample inputs and toggle outputs in a fast loop
        for _ in 0..100000 {
            i = i.wrapping_add(1);
            if i & 0x7F == 0 {
                out_high = !out_high;
                let lvl = if out_high { Level::High } else { Level::Low };
                soe.set_level(lvl);
                sspl.set_level(lvl);
                pol.set_level(lvl);
                goe.set_level(lvl);
                gspu.set_level(lvl);
                gsc.set_level(lvl);
            }

            let pk = pclk.is_high();
            if pk != last_pclk {
                pclk_toggled = true;
                last_pclk = pk;
            }

            let d = de.is_high();
            if d != last_de {
                de_toggled = true;
                last_de = d;
            }

            let hs = hsync.is_high();
            if hs != last_hsync {
                hsync_toggled = true;
                last_hsync = hs;
            }

            let vs = vsync.is_high();
            if vs != last_vsync {
                vsync_toggled = true;
                last_vsync = vs;
            }
        }

        // LED Feedback status
        if pclk_toggled && de_toggled && hsync_toggled && vsync_toggled {
            led.set_high();
            embassy_time::Timer::after_millis(100).await;
        } else {
            let blink_count = if !pclk_toggled {
                1
            } else if !de_toggled {
                2
            } else if !hsync_toggled {
                3
            } else {
                4
            };

            for _ in 0..blink_count {
                led.set_high();
                embassy_time::Timer::after_millis(150).await;
                led.set_low();
                embassy_time::Timer::after_millis(150).await;
            }
            embassy_time::Timer::after_millis(700).await;
        }
    }
}

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    loop {}
}

