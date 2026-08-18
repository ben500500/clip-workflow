---
name: Speech Recognition
slug: speech-recognition
type: system
sources:
  - path: autoclip/app/utils/speech_recognizer.py
    hash: ea106528fbbfc7efae407f14ff077052cc71edc9cc23d1ced2798d88030e0b4a
sources_digest: a2c8d8fad44d473b39fbb8fcb37f1df4151b880651ccc89aee766b6a6fd4b736
links:
  - to: ffmpeg-utilities
    relation: uses
    description: >-
      Uses ffmpeg_utils for binary paths during audio extraction and silence
      detection.
  - to: text-processing-utilities
    relation: uses
    description: Shares SRT parsing/formatting conventions with text_processor.
generator:
  version: 1
covers:
  - symbol: SpeechRecognitionMethod
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L30-L34'
  - symbol: LanguageCode
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L37-L41'
  - symbol: SpeechRecognitionConfig
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L45-L69'
  - symbol: SpeechRecognitionError
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L72-L74'
  - symbol: SpeechRecognizer
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L77-L1024'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L80-L86'
  - symbol: _check_whisper_availability
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L88-L95'
  - symbol: _check_aliyun_speech_availability
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L97-L106'
  - symbol: _check_funasr_availability
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L108-L115'
  - symbol: _extract_audio_from_video
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L117-L156'
  - symbol: generate_subtitle
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L158-L185'
  - symbol: _format_srt_timestamp
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L188-L195'
  - symbol: _segments_to_srt
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L198-L207'
  - symbol: _aggregate_word_timestamps
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L210-L288'
  - symbol: flush
    kind: function
    at: 'autoclip/app/utils/speech_recognizer.py:L243-L253'
  - symbol: _merge_short_segments
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L291-L318'
  - symbol: _detect_speech_windows
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L321-L389'
  - symbol: _split_text_by_punctuation
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L392-L429'
  - symbol: _refine_srt_with_speech_windows
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L432-L550'
  - symbol: _parse_srt_records
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L553-L581'
  - symbol: _parse_srt_time
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L584-L592'
  - symbol: _get_media_duration
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L595-L608'
  - symbol: _aliyun_speech_transcribe_audio
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L610-L673'
  - symbol: _generate_subtitle_whisper
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L675-L730'
  - symbol: _aggregate_funasr_char_timestamps
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L733-L838'
  - symbol: emit
    kind: function
    at: 'autoclip/app/utils/speech_recognizer.py:L783-L786'
  - symbol: _generate_subtitle_funasr_local
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L840-L916'
  - symbol: _strip_funasr_tags
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L919-L923'
  - symbol: _generate_subtitle_aliyun_speech
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L925-L1024'
  - symbol: generate_subtitle_for_video
    kind: function
    at: 'autoclip/app/utils/speech_recognizer.py:L1027-L1059'
---
<!-- context:generated:start -->
## Summary

Subtitle generation subsystem with three interchangeable backends: Aliyun DashScope qwen3-asr-flash API, local faster-whisper, and local FunASR. Uses 270-second segment length for Aliyun requests (configurable via AUTOCLIP_ASR_SEGMENT_SECONDS) to stay within API limits, auto-falls back between methods based on availability, and post-processes with heuristics that merge short segments and split long text across detected speech windows (via ffmpeg silencedetect) for cleaner SRT output.

## Related

- uses [[ffmpeg-utilities]] — Uses ffmpeg_utils for binary paths during audio extraction and silence detection.
- uses [[text-processing-utilities]] — Shares SRT parsing/formatting conventions with text_processor.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
