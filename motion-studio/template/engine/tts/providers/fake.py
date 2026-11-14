# -*- coding: utf-8 -*-
"""Заглушка: вместо речи — синус в mp3 расчётной длины. Сеть не открывается вовсе.

Нужна, чтобы прогнать ядро (`--rows`, `--assemble`, `--report`, кэш, манифест)
без единого платного знака и доказать, что провайдер подменяется без правки ядра.
Длина клипа — клип-модель голоса из `voices.json`: знаки × `sec_per_char_net`
плюс `clip_pad_sec`.
"""

import subprocess

from providers import Provider as Base


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


class Provider(Base):
    name = 'fake'
    emotions = None

    def list_voices(self):
        return [{'voice': vid, 'label': v.get('label', ''), 'available': True,
                 'total': len(self.cfg['voices'])}
                for vid, v in self.cfg['voices'].items()]

    def synthesize(self, text, voice_cfg, emotion, speed, pitch):
        sec = (len(text) * voice_cfg.get('sec_per_char_net', 0.057)
               + voice_cfg.get('clip_pad_sec', 0.4))
        freq = 180 + 40 * (sorted(self.cfg['voices']).index(voice_cfg['id']) % 5)
        proc = subprocess.run(
            [ffmpeg(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
             '-i', 'sine=frequency=%d:sample_rate=44100:duration=%.3f' % (freq, sec),
             '-af', 'volume=-18dB', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', '128k',
             '-f', 'mp3', 'pipe:1'],
            capture_output=True, check=True)
        return proc.stdout

    def cache_params(self, voice_cfg):
        return {'voice': voice_cfg['id'], 'rate': voice_cfg.get('sec_per_char_net'),
                'pad': voice_cfg.get('clip_pad_sec')}
