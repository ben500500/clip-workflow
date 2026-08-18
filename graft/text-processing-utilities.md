---
name: Text Processing Utilities
slug: text-processing-utilities
type: system
sources:
  - path: autoclip/app/utils/text_processor.py
    hash: 61f7ddca7e6f8541189cd0d3950e8fdde396210d9c625feccdb0f0b1016067d1
sources_digest: b79be48c63047ffb7168c123a2b133957bdbe9bc7301ffab89068768dfbfaebf
links:
  - to: speech-recognition
    relation: uses
    description: Shares SRT parsing/formatting conventions with speech_recognizer.
generator:
  version: 1
covers:
  - symbol: TextProcessor
    kind: class
    at: 'autoclip/app/utils/text_processor.py:L26-L295'
  - symbol: chunk_text
    kind: method
    at: 'autoclip/app/utils/text_processor.py:L30-L79'
  - symbol: chunk_srt_data
    kind: method
    at: 'autoclip/app/utils/text_processor.py:L81-L179'
  - symbol: parse_srt
    kind: method
    at: 'autoclip/app/utils/text_processor.py:L182-L222'
  - symbol: extract_text_by_time_range
    kind: method
    at: 'autoclip/app/utils/text_processor.py:L225-L255'
  - symbol: time_to_seconds
    kind: method
    at: 'autoclip/app/utils/text_processor.py:L258-L279'
  - symbol: seconds_to_time
    kind: method
    at: 'autoclip/app/utils/text_processor.py:L282-L295'
---
<!-- context:generated:start -->
## Summary

Text and subtitle processing utilities: chunking long text by paragraphs/sentences, parsing SRT files with encoding fallbacks, extracting text by time range, and time conversion helpers. chunk_srt_data intelligently segments subtitle lists into roughly equal time intervals by detecting pauses between entries (avoiding mid-conversation cuts), copies entries before adding temporary fields to keep originals unmodified, and falls back to forced cuts at target times when no suitable pause exists.

## Related

- uses [[speech-recognition]] — Shares SRT parsing/formatting conventions with speech_recognizer.
<!-- context:generated:end -->

## Notes

_Anything written below the generated block is preserved when the graph is regenerated._
