#!/usr/bin/env python3
"""Write a short HDR10 test clip (PQ, BT.2020) with pattern.c's bars and a moving highlight."""
import argparse
from pathlib import Path
import subprocess

WIDTH, HEIGHT, RATE = 2560, 1440, 60  # The panel refreshes at 60 Hz: one frame per refresh.
PEAK = 507.5  # pattern.c's default source peak, so the bars can be compared directly
BARS = (0, 50.75, 101.5, 203, 203 + (PEAK - 203) / 3, 203 + 2 * (PEAK - 203) / 3, PEAK)
RAMP_PEAK, HIGHLIGHT, BAND, SQUARE = 1000, 1000, 10, 160
STEP, TRACK = 8, 2880  # Constant speed: 8 px a frame, wrapping every 360 frames (6 s)


def pq(nits):
    p = (nits / 10000) ** (2610 / 16384)
    return ((3424 / 4096 + 2413 / 128 * p) / (1 + 2392 / 128 * p)) ** (2523 / 32)


def luma(nits):
    # Neutral colours: Y' carries the PQ signal (10-bit limited range); chroma is 512.
    return round(64 + 876 * pq(nits))


def row(levels):
    return b''.join(luma(v).to_bytes(2, 'little') for v in levels)


def frames(count):
    bars_end, ramp_end = HEIGHT * 3 // 5, HEIGHT * 3 // 4
    y_plane = bytearray()
    y_plane += row(BARS[x * 7 // WIDTH] for x in range(WIDTH)) * bars_end
    y_plane += row(RAMP_PEAK * x / (WIDTH - 1) for x in range(WIDTH)) * (ramp_end - bars_end)
    y_plane += row([BAND] * WIDTH) * (HEIGHT - ramp_end)
    chroma = (512).to_bytes(2, 'little') * (WIDTH // 2 * HEIGHT // 2) * 2
    square = luma(HIGHLIGHT).to_bytes(2, 'little') * SQUARE
    top = ramp_end + (HEIGHT - ramp_end - SQUARE) // 2
    for index in range(count):
        frame = bytearray(y_plane)
        # Enters at the left and leaves at the right, so a looped 6 s clip is seamless.
        left = index * STEP % TRACK - (TRACK - WIDTH) // 2
        first, last = max(left, 0), min(left + SQUARE, WIDTH)
        for y in range(top, top + SQUARE) if first < last else ():
            start = (y * WIDTH + first) * 2
            frame[start:start + (last - first) * 2] = square[:(last - first) * 2]
        yield bytes(frame) + chroma


def write(output, seconds=6):
    """Encode the clip to output (.mkv) with ffmpeg and libx265."""
    x265 = ':'.join((
        'hdr-opt=1', 'repeat-headers=1', 'range=limited', 'colorprim=bt2020', 'transfer=smpte2084',
        'colormatrix=bt2020nc', 'max-cll=1000,400',
        'master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)',
    ))
    encoder = subprocess.Popen([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'rawvideo', '-pix_fmt', 'yuv420p10le', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(RATE), '-i', '-',
        # Raw frames carry no colour properties; newer ffmpeg takes the tags from the frames.
        '-vf', 'setparams=range=tv:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc',
        '-c:v', 'libx265', '-preset', 'fast', '-crf', '12', '-pix_fmt', 'yuv420p10le', '-x265-params', x265,
        '-color_range', 'tv', '-color_primaries', 'bt2020', '-color_trc', 'smpte2084', '-colorspace', 'bt2020nc',
        '-metadata:s:v', 'title=iMac EDR test: 0-507 nit bars, 0-1000 nit ramp, 1000 nit highlight moving at 480 px/s',
        str(output),
    ], stdin=subprocess.PIPE)
    try:
        for frame in frames(seconds * RATE):
            encoder.stdin.write(frame)
    finally:
        encoder.stdin.close()
    if encoder.wait():
        raise RuntimeError('ffmpeg could not encode the HDR test clip')
    return Path(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='.mkv file to write')
    parser.add_argument('--seconds', type=int, default=6, choices=range(1, 61), metavar='1..60')
    args = parser.parse_args()
    try:
        print(write(args.output, args.seconds))
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
