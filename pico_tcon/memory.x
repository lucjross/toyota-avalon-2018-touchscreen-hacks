/* Memory map of the RP2040 (Raspberry Pi Pico), for the linker. */
MEMORY {
    /* Second-stage bootloader: first 256 bytes of flash. It configures the
       external QSPI flash so the rest of the program can execute from it. */
    BOOT2 : ORIGIN = 0x10000000, LENGTH = 0x100

    /* Program code + constants: the remaining 2 MB of external flash. */
    FLASH : ORIGIN = 0x10000100, LENGTH = 2048K - 0x100

    /* Working memory: the RP2040's 264 KB of on-chip SRAM. */
    RAM   : ORIGIN = 0x20000000, LENGTH = 264K
}
