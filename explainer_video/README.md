# Club Eligibility: The $1.46 Bouncer

A complete 3:45 animated explainer for systematic review librarians, based on [Aaron Tay's article](https://aarontay.substack.com/p/can-jev-a-super-cheap-super-fast).

## Watch and share

- `deliverables/club_eligibility.mp4`: 1920 × 1080, 24 fps, H.264/AAC, stereo sound, captions included in the picture.
- `index.html`: local player with six chapters, a transcript, source link, and downloads. Open it in a browser beside the `deliverables` folder; no internet connection is needed to play the film.
- `deliverables/script.md`: full dialogue and fact notes.
- `deliverables/club_eligibility.srt` and `.vtt`: matching captions for re-editing. Avoid displaying them over the already captioned MP4.
- `deliverables/storyboard.png`: contact sheet of fifteen scenes and transitions.
- `deliverables/poster.png`: video poster.
- The isolated voice track and stereo mix are generated locally while rendering; the WAV masters are not part of the share package.
- `deliverables/production_manifest.json`: video specification and exact revised review scores.

All illustration and animation are drawn in code. The music and sound effects are synthesized specifically for this film. Speech uses the locally installed Windows voices George, Hazel, David, Zira, and Mark. Jev has no voice. Caption timings come from speech word-boundary events and account for any timing adjustments.

For a local browser preview, run `python explainer_video/serve_player.py` and open the printed loopback URL. This server supports byte-range requests for chapter seeking. Stop it with Ctrl+C. Direct file playback remains available without a server.

## Rebuild

Requires Windows, PowerShell with `System.Speech`, the five voices named in `timeline.json`, Python with Pillow and numpy, and imageio-ffmpeg. The existing benchmark files are read; no benchmark is rerun and no provider API is called.

```powershell
python -m pip install Pillow numpy imageio-ffmpeg
& '.\explainer_video\synthesize.ps1'
& python '.\explainer_video\render_video.py' --prepare --preview --validate
& python '.\explainer_video\render_video.py' --render
& python '.\explainer_video\render_video.py' --validate
```

The `imageio-ffmpeg` package supplies the FFmpeg binary used for export. Python and its installed packages can live in a virtual environment if preferred.

Edit the authoritative dialogue in `timeline.json`; regenerate the voice clips and captions after changes. Keep the player transcript in `index.html` synchronized. The six scene functions and drawing primitives live in `render_video.py`.

## Fact handling

The eight bars come from `outputs/dta_structured_state_2026-09-30/abstract_filter_metrics.csv`, filtered to `rerun_abstract_available`. Their unweighted mean rounds to 0.661. The root README documents an older run and is deliberately not used for these bars. The revised subset has 26,832 records with abstracts and 423 relevant labels.

The reported bill and published ensemble results follow the article. The decomposition score is the probability-based expected variant, 0.5358 rounded to 0.536. The cartoon represents no fresh controlled comparison. The crystal ball belongs to the evaluator; known labels are consulted after scoring and never supplied to Jev.

The renderer checks the revised mean and record count, exact duration, caption width, voice overlap, and timing adjustments. After export, validation fully decodes video and audio to catch damaged frames or an incomplete export. Regenerateable voice clips, WAV mixes, word timings, preview frames, browser checks, and local player state are ignored by Git.
