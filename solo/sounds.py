"""Recorded CC0 dice and page turns, with synthesized sounds for the rest of the table.

Local PCM WAVs override bundled recordings; missing recordings fall back to standard-
library synthesis. Changing a synthesis recipe means raising VERSION. Split dice play
an impact from the animation's actual landing signal, not a guessed delay. The bundled
recordings' credits and CC0 dedication live in assets/sounds/README.md.
"""

import array
import cmath
import math
import os
import random
import shutil
import subprocess
import wave
from pathlib import Path

VERSION = 2
RATE = 22050
# When the Book's dice change face (book/DiceMoment.qml: 14 ticks, each longer than the
# last), and so when these rattle; they land on the last.
TICKS = [0.045 * k + 0.0016 * sum(i * i for i in range(k)) for k in range(1, 15)]
LAND = TICKS[-1]
PLAYERS = (["pw-play"], ["paplay"], ["aplay", "-q"])
# Optional local recordings. A complete set keeps the landing separate from the roll.
DICE_PARTS = ("dice-roll", "dice-roll-short", "dice-land")
BUNDLED = Path(__file__).resolve().parent.parent / "assets" / "sounds"


def names():
    return list(RECIPES)


def path(name):
    """A local override, bundled recording, or synthesized sound kept in the cache."""
    if name not in RECIPES:
        raise KeyError(name)
    override = _override(name) or _recording(BUNDLED / f"{name}.wav")
    if override is not None:
        return override
    folder = _folder()
    target = folder / f"{name}-{VERSION}.wav"
    if not target.exists():
        for old in folder.glob(f"{name}-*.wav"):
            old.unlink(missing_ok=True)
        rng = random.Random(name)
        _write(target, RECIPES[name](rng))
    return target


def dice_parts():
    """Prefer a complete local set, then the complete bundle; never mix partial sets."""
    for parts in ({name: _override(name) for name in DICE_PARTS},
                  {name: _recording(BUNDLED / f"{name}.wav") for name in DICE_PARTS}):
        if all(parts.values()):
            return {name: str(path) for name, path in parts.items()}
    return {}


def _override(name):
    base = os.environ.get("XDG_CONFIG_HOME")
    folder = (Path(base) if base else Path.home() / ".config") / "solo" / "sounds"
    return _recording(folder / f"{name}.wav")


def _recording(target):
    """Validate a bounded integer-PCM WAV before handing it to the desktop player."""
    try:
        if not target.is_file() or target.stat().st_size > 16 * 1024 * 1024:
            return None
        with wave.open(str(target), "rb") as recording:
            channels, width, rate, frames, compression, _ = recording.getparams()
            if compression != "NONE" or channels not in (1, 2) or width not in (1, 2, 3, 4):
                return None
            if not 8000 <= rate <= 192000 or not 0 < frames <= rate * 30:
                return None
            # A valid header is not enough: don't hand a truncated recording to the player.
            recording.setpos(frames - 1)
            if len(recording.readframes(1)) != channels * width:
                return None
    except (OSError, EOFError, ValueError, wave.Error):
        return None
    return target


def player(name=None):
    """The WAV player, with a gentler page turn (including local recordings)."""
    command = next((list(p) for p in PLAYERS if shutil.which(p[0])), None)
    if command and name == "page":
        if command[0] == "pw-play":
            command += ["--volume=0.75"]
        elif command[0] == "paplay":
            command += ["--volume=49152"]  # PulseAudio's full scale is 65536.
    return command


def play(name):
    """Play a sound and return at once (it carries on by itself)."""
    command = player(name)
    if not command:
        return False
    try:
        subprocess.Popen(command + [str(path(name))], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True


# The recipes -------------------------------------------------------------------------------

def dice(rng, ticks=TICKS):
    """Two dice tumbling across a wooden table, then landing: a clack of die on die at
    every change of face, a low roll underneath, a knock on the wood and two small
    settles."""
    land = ticks[-1]
    out = _silence(land + 0.5)
    for i, at in enumerate(ticks[:-1]):
        loud = 0.55 + 0.35 * rng.random()
        _add(out, _clack(rng, loud), at)
        if rng.random() < 0.6:  # the other die, a moment apart
            _add(out, _clack(rng, loud * 0.6), at + 0.008 + rng.random() * 0.018)
    rumble = _lowpass(_noise(rng, land), 260)
    _add(out, _shape(rumble, lambda t: 0.12 * (1 - t / land) ** 0.5), 0)
    _add(out, _knock(rng, 1.0), land)
    _add(out, _clack(rng, 0.9), land + 0.002)
    _add(out, _clack(rng, 0.35), land + 0.075)
    _add(out, _clack(rng, 0.18), land + 0.13)
    return _normal(out, 0.5)


def dice_short(rng):
    """The same dice, thrown quickly (the Book isn't open to watch them)."""
    return dice(rng, ticks=[0.0, 0.05, 0.11, 0.19, 0.29, 0.4, 0.5])


def dragon(rng):
    """A Dragon: bright bells running up a major chord over a warm swell, with sparkle."""
    out = _silence(2.4)
    for i, freq in enumerate((880.0, 1108.7, 1318.5, 1760.0, 2217.5)):
        _add(out, _bell(freq, 1.1, 0.5 - i * 0.05), 0.02 + i * 0.055)
    for freq in (220.0, 329.6, 440.0):
        _add(out, _pad(freq, 1.8, attack=0.08, level=0.14), 0)
    # Glitter: tiny high pings scattered over the first second, thinning out.
    for _ in range(28):
        at = 0.05 + rng.random() ** 1.5 * 1.2
        _add(out, _partial(3000 + rng.random() * 3500, 0.1, 0.07 * (1.3 - at), 0.02, attack=0.001), at)
    air = _highpass(_noise(rng, 1.4), 5000)
    _add(out, _shape(air, lambda t: 0.05 * math.exp(-t * 2.5)), 0.03)
    return _normal(out, 0.45)


def demon(rng):
    """A Demon: a low growl on a tritone, closing like a throat, over a sub boom."""
    length = 2.2
    out = _silence(length)
    growl = [a + b for a, b in zip(_saw(55.0, length), _saw(77.8, length))]
    rough = _lowpass(_noise(rng, length), 500)
    growl = [g + 0.8 * r * (0.5 + 0.5 * math.sin(2 * math.pi * 23 * i / RATE)) for i, (g, r) in enumerate(zip(growl, rough))]
    growl = _sweep_lowpass(growl, lambda t: 1400 * math.exp(-t * 1.6) + 160)
    growl = _shape(growl, lambda t: min(1, t / 0.04) * math.exp(-t * 1.3))
    _add(out, [math.tanh(1.8 * g) for g in growl], 0)
    _add(out, _thump(46, 30, 0.6, 1.0), 0)
    return _normal(out, 0.55)


def hit(rng):
    """A blow landing on the hero: a heavy thud with a crack in it."""
    out = _silence(0.6)
    _add(out, _thump(150, 48, 0.1, 1.0), 0)
    _add(out, _shape(_lowpass(_noise(rng, 0.2), 900), lambda t: 0.8 * math.exp(-t / 0.025)), 0)
    _add(out, _shape(_bandpass(_noise(rng, 0.03), 2200, 3), lambda t: 0.6 * math.exp(-t / 0.004)), 0.002)
    return _normal([math.tanh(1.5 * s) for s in out], 0.6)


def heartbeat(rng):
    """Lub-dub."""
    out = _silence(0.9)
    _add(out, _thump(68, 42, 0.08, 1.0, overtone=0.35), 0)
    _add(out, _thump(74, 45, 0.065, 0.7, overtone=0.35), 0.24)
    return _normal(out, 0.7)


def bell(rng):
    """The death knell: one stroke of a great bronze bell, left to ring out. A church
    bell's partials (hum, prime, minor third, fifth, nominal and above), each fading at
    its own pace, a pair of them beating slowly against each other."""
    length = 5.5
    out = _silence(length)
    nominal = 196.0
    partials = ((0.5, 0.5, 3.6), (1.0, 0.55, 2.8), (1.2, 0.4, 2.2), (1.203, 0.25, 2.2), (1.5, 0.22, 1.6),
                (2.0, 0.45, 1.5), (2.5, 0.16, 0.9), (2.67, 0.13, 0.8), (3.0, 0.1, 0.6), (4.0, 0.07, 0.4))
    for ratio, level, decay in partials:
        _add(out, _partial(nominal * ratio, length, level, decay, attack=0.003), 0)
    _add(out, _shape(_bandpass(_noise(rng, 0.08), 1800, 1.5), lambda t: 0.5 * math.exp(-t / 0.012)), 0)
    return _normal(out, 0.5)


def omen(rng):
    """An omen: wind moving through a narrow place, and two thin glassy tones rubbing
    against each other, rising and falling away."""
    length = 2.8
    out = _silence(length)
    wind = _noise(rng, length)
    wind = _sweep_bandpass(wind, lambda t: 450 + 450 * math.sin(math.pi * t / length) ** 2, 3.0)
    _add(out, _shape(wind, lambda t: math.sin(math.pi * t / length) ** 1.5 * 0.9), 0)
    for freq, wobble in ((1244.5, 5.0), (1318.5, 4.3)):
        tone = [math.sin(2 * math.pi * freq * i / RATE + 1.2 * math.sin(2 * math.pi * wobble * i / RATE)) for i in range(int(length * RATE))]
        _add(out, _shape(tone, lambda t: 0.1 * math.sin(math.pi * min(1, t / (length - 0.2))) ** 2), 0)
    return _normal(out, 0.35)


def page(rng):
    """A page turning: a papery swish with a crinkle or two."""
    out = _silence(0.45)
    swish = _bandpass(_noise(rng, 0.4), 2600, 0.7)
    _add(out, _shape(swish, lambda t: (t / 0.07 if t < 0.07 else math.exp(-(t - 0.07) / 0.09)) * 0.8), 0)
    for _ in range(3):
        crinkle = _bandpass(_noise(rng, 0.02), 3500 + rng.random() * 2000, 4)
        _add(out, _shape(crinkle, lambda t: 0.5 * math.exp(-t / 0.003)), 0.04 + rng.random() * 0.2)
    return _normal(out, 0.3)


def torch(rng):
    """A torch catching: a whoosh as the flame takes, then crackling."""
    length = 1.7
    out = _silence(length)
    whoosh = _sweep_lowpass(_noise(rng, 0.9), lambda t: 200 + 2600 * min(1, t / 0.35))
    _add(out, _shape(whoosh, lambda t: min(1, t / 0.3) * math.exp(-max(0, t - 0.3) / 0.18)), 0)
    for _ in range(16):
        at = 0.2 + rng.random() * 1.3
        pop = _bandpass(_noise(rng, 0.015), 1500 + rng.random() * 2500, 3)
        _add(out, _shape(pop, lambda t, a=at: (1.1 - a / length) * math.exp(-t / 0.002)), at)
    return _normal(out, 0.4)


def scene(rng):
    """A new scene: a low open fifth swelling up, as a horn would sound across a valley."""
    length = 3.2
    out = _silence(length)
    for freq, level in ((73.4, 0.5), (110.0, 0.45), (146.8, 0.35), (220.0, 0.2)):
        _add(out, _pad(freq, length, attack=0.7, level=level, bright=6), 0)
    _add(out, _pad(880.0, 2.2, attack=0.9, level=0.04), 0.4)
    return _normal(out, 0.35)


def drum(rng):
    """A war drum, twice: a fight begins."""
    out = _silence(1.3)
    for at, level in ((0.0, 1.0), (0.32, 0.85)):
        _add(out, _thump(95, 55, 0.25, level, overtone=0.3), at)
        _add(out, _shape(_bandpass(_noise(rng, 0.06), 800, 1.2), lambda t, hit=level: 0.35 * hit * math.exp(-t / 0.02)), at)
    return _normal([math.tanh(1.3 * s) for s in out], 0.6)


RECIPES = {
    "dice": dice, "dice-short": dice_short, "dragon": dragon, "demon": demon, "hit": hit, "heartbeat": heartbeat,
    "bell": bell, "omen": omen, "page": page, "torch": torch, "scene": scene, "drum": drum,
}


# Building blocks -------------------------------------------------------------------------------

def _silence(seconds):
    return [0.0] * int(seconds * RATE)


def _noise(rng, seconds):
    return [rng.uniform(-1, 1) for _ in range(int(seconds * RATE))]


def _add(out, sound, at):
    start = int(at * RATE)
    for i, s in enumerate(sound[:max(0, len(out) - start)]):
        out[start + i] += s


def _shape(sound, envelope):
    return [s * envelope(i / RATE) for i, s in enumerate(sound)]


def _normal(sound, peak):
    top = max(abs(s) for s in sound) or 1.0
    return _tail([s * peak / top for s in sound], 0.01)


def _tail(sound, seconds=0.03):
    """Fade the last moment out, so a sound cut short doesn't click."""
    fade = int(seconds * RATE)
    for i in range(min(fade, len(sound))):
        sound[-1 - i] *= i / fade
    return sound


def _lowpass(sound, cutoff):
    a = 1 - math.exp(-2 * math.pi * cutoff / RATE)
    y, out = 0.0, []
    for x in sound:
        y += a * (x - y)
        out.append(y)
    return out


def _sweep_lowpass(sound, cutoff):
    y, out = 0.0, []
    for i, x in enumerate(sound):
        y += (1 - math.exp(-2 * math.pi * cutoff(i / RATE) / RATE)) * (x - y)
        out.append(y)
    return out


def _highpass(sound, cutoff):
    return [x - y for x, y in zip(sound, _lowpass(sound, cutoff))]


def _bandpass(sound, centre, q):
    w = 2 * math.pi * centre / RATE
    alpha = math.sin(w) / (2 * q)
    b, c1, c2 = alpha / (1 + alpha), 2 * math.cos(w) / (1 + alpha), (1 - alpha) / (1 + alpha)
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for x in sound:
        y = b * (x - x2) + c1 * y1 - c2 * y2
        x2, x1, y2, y1 = x1, x, y1, y
        out.append(y)
    return out


def _sweep_bandpass(sound, centre, q):
    """A resonant band (a biquad, constant peak gain) whose centre can move."""
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for i, x in enumerate(sound):
        w = 2 * math.pi * centre(i / RATE) / RATE
        alpha = math.sin(w) / (2 * q)
        a0 = 1 + alpha
        y = (alpha * x - alpha * x2 + 2 * math.cos(w) * y1 - (1 - alpha) * y2) / a0
        x2, x1, y2, y1 = x1, x, y1, y
        out.append(y)
    return out


def _partial(freq, seconds, level, decay, attack=0.002):
    """A sine that strikes and dies away (turned, sample by sample, as a complex number)."""
    turn = cmath.exp(complex(-1 / (decay * RATE), 2 * math.pi * freq / RATE))
    rise = max(1.0, attack * RATE)
    z, out = complex(level, 0), []
    for i in range(int(seconds * RATE)):
        out.append(z.imag * (i / rise if i < rise else 1.0))
        z *= turn
    return _tail(out)


def _bell(freq, seconds, level):
    """A small bright bell: a fundamental and two inharmonic partials that die quickly."""
    tone = _partial(freq, seconds, level, seconds * 0.45)
    for ratio, share, decay in ((2.76, 0.3, 0.15), (5.4, 0.12, 0.06)):
        for i, s in enumerate(_partial(freq * ratio, seconds, level * share, decay)):
            tone[i] += s
    return tone


def _pad(freq, seconds, attack, level, bright=2):
    """A soft held note with a few harmonics, swelling in and dying away."""
    tone = _oscillator(freq, seconds, [1 / (h * h) for h in range(1, bright + 1)])
    return _tail(_shape(tone, lambda t: level * math.sin(math.pi / 2 * min(1, t / attack)) ** 2 * math.exp(-max(0, t - attack) / (seconds * 0.4))))


def _saw(freq, seconds):
    """A band-limited sawtooth (harmonics up to about 2 kHz)."""
    return _oscillator(freq, seconds, [0.5 / h for h in range(1, max(1, int(2000 // freq)) + 1)])


def _oscillator(freq, seconds, harmonics, size=4096):
    """A steady tone with the given harmonic amplitudes, read from one cycle drawn once."""
    cycle = [sum(a * math.sin(2 * math.pi * (h + 1) * i / size) for h, a in enumerate(harmonics)) for i in range(size)]
    step = freq * size / RATE
    return [cycle[int(i * step) % size] for i in range(int(seconds * RATE))]


def _thump(start, end, decay, level, overtone=0.0):
    """A low drum-like thump: a sine falling in pitch, with a little of its octave so
    small speakers carry it."""
    n = int((decay * 6) * RATE)
    phase, out = 0.0, []
    for i in range(n):
        t = i / RATE
        freq = end + (start - end) * math.exp(-t / 0.04)
        phase += 2 * math.pi * freq / RATE
        out.append(level * min(1, t / 0.002) * math.exp(-t / decay) * (math.sin(phase) + overtone * math.sin(2 * phase)))
    return _tail(out)


def _clack(rng, level):
    """Die on die, or die on wood: a click with a small hard ring."""
    ring = _partial(1400 + rng.random() * 1400, 0.03, level * 0.5, 0.008, attack=0.0005)
    click = _shape(_bandpass(_noise(rng, 0.012), 2400 + rng.random() * 1800, 2.5), lambda t: level * math.exp(-t / 0.0025))
    return [a + b for a, b in zip(ring, click + [0.0] * len(ring))]


def _knock(rng, level):
    """The dice striking the table as they come to rest: a low wooden knock."""
    body = [a + b for a, b in zip(_partial(185, 0.25, level * 0.7, 0.045, attack=0.001), _partial(112, 0.25, level * 0.6, 0.07, attack=0.001))]
    dull = _shape(_lowpass(_noise(rng, 0.05), 1200), lambda t: level * 0.5 * math.exp(-t / 0.008))
    return [a + b for a, b in zip(body, dull + [0.0] * len(body))]


def _write(target, sound):
    samples = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in sound))
    partial = target.with_suffix(".part")
    with wave.open(str(partial), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    partial.replace(target)


def _folder():
    base = os.environ.get("XDG_CACHE_HOME")
    folder = (Path(base) if base else Path.home() / ".cache") / "solo-play" / "sounds"
    folder.mkdir(parents=True, exist_ok=True)
    return folder
