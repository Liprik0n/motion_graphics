// Заглушка ffprobe для HyperFrames. Настоящего ffprobe на машине может не быть: imageio_ffmpeg
// приносит только ffmpeg. HyperFrames требует ffprobe при запуске, хотя для немой композиции,
// отрендеренной в png-sequence, его не зовёт: звук ролика сводит наш ffmpeg (build.py).
// Если ffprobe всё же позовут — громкий отказ, а не выдуманный ответ.
using System;
class FfprobeStub {
    static int Main(string[] args) {
        Console.Error.WriteLine("ffprobe stub (engine/video/tools): media probing is disabled here; " +
            "compositions must not contain <audio>/<video>. Args: " + string.Join(" ", args));
        return 3;
    }
}
