$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
public class JevSpeechWord {
    public int Position { get; set; }
    public int Length { get; set; }
    public double Seconds { get; set; }
}
public class JevSpeechTimingCapture {
    public List<JevSpeechWord> Items = new List<JevSpeechWord>();
    public void Handle(object sender, EventArgs e) {
        var t = e.GetType();
        Items.Add(new JevSpeechWord {
            Position = (int)t.GetProperty("CharacterPosition").GetValue(e),
            Length = (int)t.GetProperty("CharacterCount").GetValue(e),
            Seconds = ((TimeSpan)t.GetProperty("AudioPosition").GetValue(e)).TotalSeconds
        });
    }
}
'@
$taskBase = $PSScriptRoot
$taskTimeline = Get-Content -LiteralPath (Join-Path $taskBase 'timeline.json') -Raw | ConvertFrom-Json
$taskAudio = Join-Path $taskBase 'audio'
New-Item -ItemType Directory -Path $taskAudio -Force | Out-Null
$taskSynth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$taskCapture = [JevSpeechTimingCapture]::new()
$taskEvent = $taskSynth.GetType().GetEvent('SpeakProgress')
$taskHandler = [Delegate]::CreateDelegate($taskEvent.EventHandlerType, $taskCapture, $taskCapture.GetType().GetMethod('Handle'), $true)
$taskEvent.AddEventHandler($taskSynth, $taskHandler)
try {
    # The installed engine reports word boundaries on a 16 kHz clock.
    # Preserve that rate here; resample the finished waveform in Python.
    $taskFormat = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    for ($taskIndex = 0; $taskIndex -lt $taskTimeline.cues.Count; $taskIndex++) {
        $taskCue = $taskTimeline.cues[$taskIndex]
        $taskVoice = $taskTimeline.voices.($taskCue.speaker)
        $taskSynth.SelectVoice($taskVoice)
        $taskSynth.Rate = if ($taskCue.speaker -eq 'Narrator') { 1 } else { 0 }
        $taskSynth.Volume = 100
        $taskCapture.Items.Clear()
        $taskFilename = '{0:D2}.wav' -f $taskIndex
        $taskTarget = Join-Path $taskAudio $taskFilename
        $taskSynth.SetOutputToWaveFile($taskTarget, $taskFormat)
        $taskSynth.Speak($taskCue.text)
        $taskSynth.SetOutputToNull()
        $taskCapture.Items | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $taskAudio ('{0:D2}.json' -f $taskIndex)) -Encoding utf8
        Write-Output ('Voice {0:D2}: {1}' -f $taskIndex, $taskCue.speaker)
    }
} finally {
    $taskEvent.RemoveEventHandler($taskSynth, $taskHandler)
    $taskSynth.Dispose()
}
