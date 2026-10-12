"""Minimal drawing on the Linux framebuffer (32-bit pixels, bytes B, G, R, unused).

The head unit's /dev/fb0 is 776x468; set HU_FB (a path) and HU_FB_SIZE (WxH) to draw
into an ordinary file instead, which is how the games are tested off the Pi.
"""

import fcntl
import mmap
import os
import stat

KDSETMODE = 0x4B3A
KD_TEXT, KD_GRAPHICS = 0, 1


class Framebuffer:
    def __init__(self):
        path = os.environ.get("HU_FB", "/dev/fb0")
        if "HU_FB_SIZE" in os.environ:
            self.width, self.height = map(int, os.environ["HU_FB_SIZE"].split("x"))
            self.stride = self.width * 4
        else:
            sysfs = "/sys/class/graphics/fb0"
            self.width, self.height = map(int, open(f"{sysfs}/virtual_size").read().split(","))
            self.stride = int(open(f"{sysfs}/stride").read())
            if int(open(f"{sysfs}/bits_per_pixel").read()) != 32:
                raise RuntimeError("framebuffer is not 32 bits per pixel")
        size = self.stride * self.height
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT)
        info = os.fstat(self.fd)
        if stat.S_ISREG(info.st_mode) and info.st_size < size:
            os.ftruncate(self.fd, size)  # the test file; a real framebuffer is a device
        self.mem = mmap.mmap(self.fd, size)

    @staticmethod
    def pixel(color):
        r, g, b = color
        return bytes((b, g, r, 0))

    def fill(self, color):
        self.mem[:] = self.pixel(color) * (len(self.mem) // 4)

    def rect(self, x, y, w, h, pixel):
        """Fill a rectangle (already converted with pixel()), clipped to the screen."""
        x0, x1 = max(x, 0), min(x + w, self.width)
        y0, y1 = max(y, 0), min(y + h, self.height)
        if x0 >= x1 or y0 >= y1:
            return
        row = pixel * (x1 - x0)
        for yy in range(y0, y1):
            off = yy * self.stride + x0 * 4
            self.mem[off:off + len(row)] = row

    def put(self, x, y, pixel):
        """Write one pixel (already converted with pixel()). Out-of-range is ignored."""
        if 0 <= x < self.width and 0 <= y < self.height:
            off = y * self.stride + x * 4
            self.mem[off:off + 4] = pixel

    def close(self):
        self.mem.close()
        os.close(self.fd)


def console_graphics(on):
    """Stop the text console drawing over the framebuffer (and give it back afterwards).

    Needs access to /dev/tty1; if that's not available the games still run, the console
    cursor just may show through.
    """
    try:
        fd = os.open("/dev/tty1", os.O_RDWR)
    except OSError:
        return
    try:
        fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS if on else KD_TEXT)
    except OSError:
        pass
    finally:
        os.close(fd)
