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
    at: 'autoclip/app/utils/speech_recognizer.py:L30-L35'
  - symbol: LanguageCode
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L38-L42'
  - symbol: SpeechRecognitionConfig
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L46-L73'
  - symbol: SpeechRecognitionError
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L76-L78'
  - symbol: SpeechRecognizer
    kind: class
    at: 'autoclip/app/utils/speech_recognizer.py:L81-L1166'
  - symbol: __init__
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L84-L90'
  - symbol: _check_whisper_availability
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L92-L99'
  - symbol: _check_aliyun_speech_availability
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L101-L110'
  - symbol: _check_funasr_availability
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L112-L119'
  - symbol: _extract_audio_from_video
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L121-L160'
  - symbol: generate_subtitle
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L162-L191'
  - symbol: _format_srt_timestamp
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L194-L201'
  - symbol: _segments_to_srt
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L204-L213'
  - symbol: _aggregate_word_timestamps
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L216-L294'
  - symbol: flush
    kind: function
    at: 'autoclip/app/utils/speech_recognizer.py:L249-L259'
  - symbol: _merge_short_segments
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L297-L324'
  - symbol: _detect_speech_windows
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L327-L395'
  - symbol: _split_text_by_punctuation
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L398-L435'
  - symbol: _refine_srt_with_speech_windows
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L438-L556'
  - symbol: _parse_srt_records
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L559-L587'
  - symbol: _parse_srt_time
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L590-L598'
  - symbol: _get_media_duration
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L601-L614'
  - symbol: _aliyun_speech_transcribe_audio
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L616-L679'
  - symbol: _mimo_asr_transcribe_audio
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L682-L738'
  - symbol: _generate_subtitle_whisper
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L740-L795'
  - symbol: _aggregate_funasr_char_timestamps
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L798-L903'
  - symbol: emit
    kind: function
    at: 'autoclip/app/utils/speech_recognizer.py:L848-L851'
  - symbol: _generate_subtitle_funasr_local
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L905-L984'
  - symbol: _generate_subtitle_mimo_asr
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L988-L1058'
  - symbol: _strip_funasr_tags
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L1061-L1065'
  - symbol: _generate_subtitle_aliyun_speech
    kind: method
    at: 'autoclip/app/utils/speech_recognizer.py:L1067-L1166'
  - symbol: generate_subtitle_for_video
    kind: function
    at: 'autoclip/app/utils/speech_recognizer.py:L1169-L1212'
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
