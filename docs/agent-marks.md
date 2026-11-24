# Agent identification

The local report uses native log formats to identify Claude Code and Codex.
It does not label Codex sessions as ChatGPT sessions.
Unknown hosts receive a neutral icon.

The marks identify the recorded model family or provider. Host labels remain separate.
They do not indicate affiliation with Kyma or an enforcement verdict.

The report embeds these first-party assets, retrieved November 24, 2026:

| Identity | Asset and first-party reference |
| --- | --- |
| Anthropic / Claude | [Orange Claude icon](https://claude.com/icon.svg), linked by [Claude](https://claude.com/). |
| OpenAI | White blossom SVG from the [official logo archive](https://cdn.openai.com/brand/openai-logos.zip). |
| Google | [Google G](https://www.gstatic.com/images/branding/product/1x/googleg_48dp.png). |
| Gemini | [Gemini sparkle](https://www.gstatic.com/lamda/images/gemini_sparkle_4g_512_lt_f94943af3be039176192d.png), linked by [Gemini](https://gemini.google.com/). |
| DeepSeek | [DeepSeek favicon](https://deepseek.com/favicon.ico), linked by [DeepSeek](https://www.deepseek.com/). |
| Mistral | The compact, colored mobile header mark from [Mistral](https://mistral.ai/). Its native viewBox is `0 0 21 15`. |
| xAI / Grok | [Grok app icon](https://grok.com/images/android-chrome-192x192.png), linked by [Grok](https://grok.com/). |
| Qwen | [Qwen icon](https://img.alicdn.com/imgextra/i4/O1CN01OXv3EM1FN8t9W4P79_!!6000000000474-2-tps-80-80.png), linked by [Qwen](https://qwen.ai/). |
| Meta / Llama | [Meta infinity icon](https://static.xx.fbcdn.net/rsrc.php/yf/r/-7pQO6hUGK_.svg), linked by [Meta brand resources](https://about.meta.com/brand/resources/meta/company-brand/). |

The embedded SVGs preserve their original path geometry, viewBox, and color.
PNG assets preserve their source pixels. DeepSeek's ICO becomes a lossless PNG with identical decoded RGBA pixels.
The registry uses data-URI images. SVG gradient identifiers stay inside their image documents, so repeated marks cannot conflict.
No mark requires a network request. The marks remain their owners' trademarks and are not licensed as Kyma code.
See the [OpenAI brand guidelines](https://openai.com/brand/) and [Anthropic trademark guidelines](https://assets.claude.com/f7874b435aabdaee5f836e888b4439b9b56a934b.pdf).

The Gemini sparkle applies to Gemini models. Other Google families can use the Google G.
An icon does not establish support for that provider's native transcript format.
Unknown or mixed providers retain a neutral mark. They must not silently inherit Claude or OpenAI identity.

Model and effort values come from the corresponding transcript metadata.
The selected action uses its own recorded configuration. A later model choice cannot identify an earlier action.
Unknown values stay unknown. Effort is a recorded configuration, not a measure of intelligence.
