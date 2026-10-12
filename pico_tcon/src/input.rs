//! Front-panel rotary encoders + pushbuttons, reported to the Pi as text lines over USB CDC serial.
//!
//! The Pico knows nothing about "modes" or what a knob means: it just says which encoder turned
//! (`E1 +1` / `E1 -1`) and which button changed (`B1 down` / `B1 up`). The Pi daemon decides what
//! those do. This runs entirely on cooperative tasks, so it never disturbs the PIO state machines
//! that generate the display timing.
//!
//! Encoder 1 = volume knob (has detents): reports one step per detent.
//! Encoder 2 = tuning knob (no detents): reports one step per quadrature edge (4 per cycle) for
//! fine resolution; the Pi scales it as needed.

use embassy_futures::select::select;
use embassy_rp::gpio::Input;
use embassy_rp::peripherals::USB;
use embassy_rp::usb::Driver;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use embassy_time::Timer;
use embassy_usb::class::cdc_acm::Sender;

pub enum Event {
    /// Encoder `id` moved: +1 clockwise, -1 counter-clockwise.
    Turn(u8, i8),
    /// Button `id` changed state (true = pressed).
    Button(u8, bool),
}

pub static EVENTS: Channel<CriticalSectionRawMutex, Event, 32> = Channel::new();

/// How an encoder's quadrature signal is turned into steps.
#[derive(Clone, Copy)]
pub enum Decode {
    /// Step only at detent rest positions (debounces contact bounce via the state table).
    Detent,
    /// Step on every valid edge; for knobs with no detents.
    EveryEdge,
}

// Half-step quadrature decoder table (same algorithm as the old Pi Python code).
// Rows = current state, columns = (CLK << 1) | DT. Result bits 0x10 = CW step, 0x20 = CCW step.
const S: u8 = 0x00;
const CW: u8 = 0x10;
const CC: u8 = 0x20;
const SM: u8 = 0x03;
const CWB: u8 = 0x02;
const CCB: u8 = 0x01;
const CWBM: u8 = 0x04;
const CCBM: u8 = 0x05;
const HALF_TAB: [[u8; 4]; 6] = [
    [SM, CWB, CCB, S],
    [SM | CC, S, CCB, S],
    [SM | CW, CWB, S, S],
    [SM, CCBM, CWBM, S],
    [SM, SM, CWBM, S | CW],
    [SM, CCBM, SM, S | CC],
];

// Full-resolution delta, indexed by (previous_pins << 2) | new_pins where pins = (CLK << 1) | DT.
// Gray-code sequence 11 -> 01 -> 00 -> 10 is +1 (clockwise, same sense as HALF_TAB above); the
// reverse is -1. Jumps of two (0) are bounce.
const EDGE_DELTA: [i8; 16] = [0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0];

#[embassy_executor::task(pool_size = 2)]
pub async fn encoder_task(id: u8, decode: Decode, mut clk: Input<'static>, mut dt: Input<'static>) {
    let mut state = 0u8;
    let mut prev = ((clk.is_high() as usize) << 1) | dt.is_high() as usize;
    loop {
        // Wake on any edge of either pin, then feed both levels to the decoder.
        select(clk.wait_for_any_edge(), dt.wait_for_any_edge()).await;
        let pins = ((clk.is_high() as usize) << 1) | dt.is_high() as usize;
        let delta = match decode {
            Decode::Detent => {
                state = HALF_TAB[(state & 0x0f) as usize][pins];
                match state & 0x30 {
                    CW => 1,
                    CC => -1,
                    _ => 0,
                }
            }
            Decode::EveryEdge => EDGE_DELTA[(prev << 2) | pins],
        };
        prev = pins;
        if delta != 0 {
            EVENTS.send(Event::Turn(id, delta)).await;
        }
    }
}

#[embassy_executor::task(pool_size = 2)]
pub async fn button_task(id: u8, mut sw: Input<'static>) {
    // Pulled up, so low = pressed.
    let mut pressed = sw.is_low();
    loop {
        sw.wait_for_any_edge().await;
        Timer::after_millis(10).await; // let contact bounce settle, then trust the level
        let now = sw.is_low();
        if now != pressed {
            pressed = now;
            EVENTS.send(Event::Button(id, pressed)).await;
        }
    }
}

/// Forwards events to the host. Waits for the port to be opened; if the host goes away the
/// write fails and we go back to waiting.
#[embassy_executor::task]
pub async fn report_task(mut tx: Sender<'static, Driver<'static, USB>>) {
    loop {
        tx.wait_connection().await;
        loop {
            let ev = EVENTS.receive().await;
            let line: &[u8] = match ev {
                Event::Turn(1, 1) => b"E1 +1\n",
                Event::Turn(1, _) => b"E1 -1\n",
                Event::Turn(_, 1) => b"E2 +1\n",
                Event::Turn(_, _) => b"E2 -1\n",
                Event::Button(1, true) => b"B1 down\n",
                Event::Button(1, false) => b"B1 up\n",
                Event::Button(_, true) => b"B2 down\n",
                Event::Button(_, false) => b"B2 up\n",
            };
            if tx.write_packet(line).await.is_err() {
                break;
            }
        }
    }
}
