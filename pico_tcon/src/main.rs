#![no_std]
#![no_main]

mod input;

use embassy_executor::Spawner;
use embassy_rp::bind_interrupts;
use embassy_rp::gpio::{Input, Pull};
use embassy_rp::peripherals::{PIO0, PIO1, USB};
use embassy_rp::pio::program::pio_asm;
use embassy_rp::pio::{Config, Direction, InterruptHandler, Pio};
use embassy_rp::usb;
use embassy_usb::class::cdc_acm::{CdcAcmClass, State};
use embassy_usb::UsbDevice;
use static_cell::StaticCell;

bind_interrupts!(struct Irqs {
    PIO0_IRQ_0 => InterruptHandler<PIO0>;
    PIO1_IRQ_0 => InterruptHandler<PIO1>;
    USBCTRL_IRQ => usb::InterruptHandler<USB>;
});

/// Services the USB bus (enumeration, transfers) for as long as the device runs.
#[embassy_executor::task]
async fn usb_task(mut device: UsbDevice<'static, usb::Driver<'static, USB>>) -> ! {
    device.run().await
}

#[embassy_executor::main]
async fn main(spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    // Configure onboard LED (GP25) as Output
    let _led_pin = embassy_rp::gpio::Output::new(p.PIN_25, embassy_rp::gpio::Level::Low);

    // ── PIO0: SSPL, SOE, GOE ──────────────────────────────────────────────
    let Pio {
        mut common,
        mut sm0, // SSPL
        mut sm1, // SOE
        mut sm2, // GOE
        ..
    } = Pio::new(p.PIO0, Irqs);

    // Inputs from Pi: GP2=SSC, GP3=DE, GP4=HSYNC.
    // Outputs: GP5=SOE, GP6=SSPL, GP8=GOE.
    let _ssc = common.make_pio_pin(p.PIN_2);
    let _de = common.make_pio_pin(p.PIN_3);
    let _hsync = common.make_pio_pin(p.PIN_4);
    let soe_pin = common.make_pio_pin(p.PIN_5);
    let sspl_pin = common.make_pio_pin(p.PIN_6);
    let goe_pin = common.make_pio_pin(p.PIN_8);

    // SSPL: ~1-SSC start pulse, one per line. Trigger on the HSYNC rising edge
    // (back porch start) and run a system-clock delay (~344 cyc) to reach the first
    // active pixel — htotal÷4 phase-locks this delay to SSC, so it does NOT drift.
    // Then fire the rising edge DIRECTLY, with NO SSC-align before it.
    //
    // The SSC-align is deliberately omitted: a "wait gpio 2" before the rising edge
    // resolves the DE/SSC coincidence ±1 differently each line, which is what caused
    // the horizontal shimmer. Firing directly off the phase-locked delay is both
    // centered and jitter-free. (Post-rising waits are fine — they only set the pulse
    // width, not its position.) gpio 4 = HSYNC, gpio 2 = SSC.
    let sspl_prg = pio_asm!(
        ".wrap_target",
        "wait 0 gpio 4",      // wait for HSYNC low
        "wait 1 gpio 4",      // HSYNC high (back porch start)
        "set y, 7",           // 8 outer loops
        "sspl_y:",
        "set x, 7",           // 8 inner loops
        "sspl_x:",
        "jmp x-- sspl_x [4]", // 5 cycles per inner loop
        "jmp y-- sspl_y [1]", // ~344 cycles total -> lands ~at DE (centered)
        "set pins, 1",        // fire DIRECTLY — no SSC-align (the jitter source)
        "wait 0 gpio 2",      // hold ~one SSC period (post-rising waits are safe)
        "wait 1 gpio 2",
        "set pins, 0",        // SSPL low
        ".wrap",
    );

    // SOE: source output enable. The datasheet specifies that SOE is a line latch strobe,
    // NOT a level, and should emit a brief ~2-clock pulse after the last pixel of the line.
    // SOE switches the source lines to the next line's data, so it must not fire until the
    // gate has actually closed: GOE goes high at the DE falling edge, but the gate outputs
    // take up to 900 ns to turn off (trpd). We wait ~1.28 us (160 cycles) first, then add
    // the 1 clock Tld delay before raising SOE. Still far ahead of the next SSPL (Tlds).
    // gpio 3 = DE, gpio 2 = SSC.
    let soe_prg = pio_asm!(
        ".wrap_target",
        "wait 1 gpio 3",      // wait for DE high
        "wait 0 gpio 3",      // wait for DE low
        "set x, 19",          // gate-off delay: 20 * 8 = 160 cycles = 1.28 us at 125MHz
    "soe_delay:",
        "jmp x-- soe_delay [7]",
        "wait 1 gpio 2",      // wait 1 clock cycle (Tld delay)
        "wait 0 gpio 2",
        "set pins, 1",        // SOE high
        "wait 1 gpio 2",      // clock 1
        "wait 0 gpio 2",
        "wait 1 gpio 2",      // clock 2
        "wait 0 gpio 2",
        "set pins, 0",        // SOE low
        ".wrap",
    );

    // GOE: gate output enable. HIGH blanks the gate outputs; LOW lets the gate
    // follow the scan (selected row on). Idle LOW (enabled); at each HSYNC edge
    // (the gate-clock row advance) emit a brief ~1.5 us HIGH blip to blank the
    // transition so adjacent rows don't overlap. That blanking is what isolates
    // the rows. Datasheet GOE pulse width >=1us. gpio 3 = DE.
    let goe_prg = pio_asm!(
        "set pins, 1",        // idle HIGH: gate disabled (blanked)
        ".wrap_target",
        "wait 1 gpio 3",      // wait for DE high (active video starts)
        "set x, 31",          // 2.3 us delay (32 * 9 = 288 cycles at 125MHz)
    "goe_delay:",
        "jmp x-- goe_delay [8]",
        "set pins, 0",        // GOE low: enable gates ONLY AFTER old row is off
        "wait 0 gpio 3",      // wait for DE low (blanking starts)
        "set pins, 1",        // GOE high: blank porches and transition
        ".wrap",
    );

    let loaded_sspl = common.load_program(&sspl_prg.program);
    let loaded_soe = common.load_program(&soe_prg.program);
    let loaded_goe = common.load_program(&goe_prg.program);

    let mut cfg0 = Config::default();
    cfg0.use_program(&loaded_sspl, &[]);
    cfg0.set_set_pins(&[&sspl_pin]);
    sm0.set_config(&cfg0);
    sm0.set_pin_dirs(Direction::Out, &[&sspl_pin]);
    sm0.set_enable(true);

    let mut cfg1 = Config::default();
    cfg1.use_program(&loaded_soe, &[]);
    cfg1.set_set_pins(&[&soe_pin]);
    sm1.set_config(&cfg1);
    sm1.set_pin_dirs(Direction::Out, &[&soe_pin]);
    sm1.set_enable(true);

    let mut cfg2 = Config::default();
    cfg2.use_program(&loaded_goe, &[]);
    cfg2.set_set_pins(&[&goe_pin]);
    sm2.set_config(&cfg2);
    sm2.set_pin_dirs(Direction::Out, &[&goe_pin]);
    sm2.set_enable(true);

    // ── PIO1: GSPU, GSC, POL ──────────────────────────────────────────────
    let Pio {
        common: mut common1,
        sm0: mut gspu_sm,
        sm1: mut gsc_sm,
        sm2: mut pol_sm,
        ..
    } = Pio::new(p.PIO1, Irqs);

    let gspu_pin = common1.make_pio_pin(p.PIN_10);
    let gsc_pin = common1.make_pio_pin(p.PIN_11);
    let pol_pin = common1.make_pio_pin(p.PIN_7);

    // GSPU: one clean token per frame. At the frame's VSYNC, skip one HSYNC
    // edge (so GSPU is high a full line before it loads — far exceeds the 200ns
    // setup), then go high across exactly the next HSYNC/GSC edge (token loads
    // at row 0), hold ~1us (>> 300ns hold), then drop before the following edge
    // so no second token. gpio 9 = VSYNC, gpio 4 = HSYNC.
    let gspu_prg = pio_asm!(
        "set pins, 0",        // GSPU idle low
        ".wrap_target",
    "wait_vsync_low:",
        "wait 0 gpio 9",      // wait VSYNC low
    "wait_vsync_high:",
        "wait 1 gpio 9",      // VSYNC rising = frame start
        "set x, 31",          // start VSYNC-HSYNC bypass delay
    "vsync_delay:",
        "jmp x-- vsync_delay [31]", // delay ~8 us (1024 cycles) to step past HSYNC transition window
        "wait 0 gpio 4",      // wait for HSYNC to go low (first line's blanking start)
        "set pins, 1",        // GSPU high (starts setup before GSC rising)
        "set y, 15",          // delay 1 us (128 cycles)
    "gspu_hold:",
        "jmp y-- gspu_hold [7]", // 16 * 8 = 128 cycles ≈ 1.0 us
        "set pins, 0",        // GSPU low
        "wait 0 gpio 9",      // wait VSYNC low (end of frame) to prevent re-triggering
        ".wrap",
    );

    // GSC: gate clock with ONE clean advance edge per line, during horizontal blanking.
    // At each HSYNC falling edge drop GSC low, wait ~512 ns, then raise it — that rising
    // edge advances the gate while GOE has the outputs blanked (DE low), so the row
    // transition draws no current on the active line. Doing this advance mid-active-line
    // (the old behavior) dumped current spikes into the rails and caused the line shimmer.
    // gpio 4 = HSYNC.
    let gsc_prg = pio_asm!(
        "set pins, 0",
        ".wrap_target",
        "wait 0 gpio 4",      // HSYNC falling edge
        "set pins, 0",        // GSC low
        "irq nowait 4",       // tell POL (same PIO block) a filtered line edge happened
        "set x, 31",          // delay 512 ns (64 cycles at 125MHz)
    "gsc_delay:",
        "jmp x-- gsc_delay [1]",
        "set pins, 1",        // GSC high: row advance during blanking
        "wait 1 gpio 4",      // wait HSYNC high
        "set x, 15",          // ~240ns debounce after HSYNC rising. REQUIRED: without it GSC
    "gsc_debounce:",          // re-triggers on HSYNC glitches -> gate advances multiple times
        "jmp x-- gsc_debounce [1]", // per line -> scan runs too fast -> image repeats in vertical thirds.
        ".wrap",
    );

    // POL: 1-line inversion, toggled once per line (during blanking). It does not watch HSYNC
    // itself: the GSC state machine raises PIO flag 4 on each HSYNC edge it has already
    // filtered, so POL toggles exactly as often as the gate advances. Watching the raw pin
    // here would double-toggle on HSYNC ringing, and DC balance needs an odd toggle count
    // per frame (527).
    let pol_prg = pio_asm!(
        "set y, 0",
        ".wrap_target",
        "wait 1 irq 4",       // wait for GSC's line flag (and clear it)
        "mov pins, y",        // set POL to current polarity
        "mov y, ~y",          // toggle polarity
        ".wrap",
    );

    let loaded_gspu = common1.load_program(&gspu_prg.program);
    let loaded_gsc = common1.load_program(&gsc_prg.program);
    let loaded_pol = common1.load_program(&pol_prg.program);

    let mut cfg_g = Config::default();
    cfg_g.use_program(&loaded_gspu, &[]);
    cfg_g.set_set_pins(&[&gspu_pin]);
    gspu_sm.set_config(&cfg_g);
    gspu_sm.set_pin_dirs(Direction::Out, &[&gspu_pin]);
    gspu_sm.set_enable(true);

    let mut cfg_gsc = Config::default();
    cfg_gsc.use_program(&loaded_gsc, &[]);
    cfg_gsc.set_set_pins(&[&gsc_pin]);
    gsc_sm.set_config(&cfg_gsc);
    gsc_sm.set_pin_dirs(Direction::Out, &[&gsc_pin]);
    gsc_sm.set_enable(true);

    let mut cfg_pol = Config::default();
    cfg_pol.use_program(&loaded_pol, &[]);
    cfg_pol.set_set_pins(&[&pol_pin]);
    cfg_pol.set_out_pins(&[&pol_pin]);
    pol_sm.set_config(&cfg_pol);
    pol_sm.set_pin_dirs(Direction::Out, &[&pol_pin]);
    pol_sm.set_enable(true);

    let mut _pin_vsync = embassy_rp::gpio::Input::new(p.PIN_9, embassy_rp::gpio::Pull::None);

    // ── Front-panel encoders → USB CDC serial to the Pi ───────────────────
    // E1 volume (detented): GP16 CLK, GP17 DT, GP18 SW.  E2 tuning (no detents): GP19/GP20/GP21.
    // Inputs use the internal pull-up; wire the common to GND.
    spawner.spawn(
        input::encoder_task(
            1,
            input::Decode::Detent,
            Input::new(p.PIN_16, Pull::Up),
            Input::new(p.PIN_17, Pull::Up),
        )
        .unwrap(),
    );
    spawner.spawn(input::button_task(1, Input::new(p.PIN_18, Pull::Up)).unwrap());
    spawner.spawn(
        input::encoder_task(
            2,
            input::Decode::EveryEdge,
            Input::new(p.PIN_19, Pull::Up),
            Input::new(p.PIN_20, Pull::Up),
        )
        .unwrap(),
    );
    spawner.spawn(input::button_task(2, Input::new(p.PIN_21, Pull::Up)).unwrap());

    let driver = usb::Driver::new(p.USB, Irqs);
    let mut config = embassy_usb::Config::new(0x16c0, 0x27dd);
    config.manufacturer = Some("toyota-etch");
    config.product = Some("Head unit controls");
    config.serial_number = Some("0001");

    static CONFIG_DESC: StaticCell<[u8; 256]> = StaticCell::new();
    static BOS_DESC: StaticCell<[u8; 256]> = StaticCell::new();
    static CONTROL_BUF: StaticCell<[u8; 64]> = StaticCell::new();
    static CDC_STATE: StaticCell<State> = StaticCell::new();
    let mut builder = embassy_usb::Builder::new(
        driver,
        config,
        CONFIG_DESC.init([0; 256]),
        BOS_DESC.init([0; 256]),
        &mut [], // no Microsoft OS descriptors
        CONTROL_BUF.init([0; 64]),
    );
    let class = CdcAcmClass::new(&mut builder, CDC_STATE.init(State::new()), 64);
    let (tx, _rx) = class.split();
    spawner.spawn(usb_task(builder.build()).unwrap());
    spawner.spawn(input::report_task(tx).unwrap());

    loop {
        embassy_time::Timer::after_secs(3600).await;
    }
}

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    loop {}
}
