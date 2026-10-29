# Third-party notices

## Kargul Calendar Design

The LeadFinder workspace layout and design tokens are adapted from
[kargulstudio/calender-app-design](https://github.com/kargulstudio/calender-app-design),
reference commit `b4a9e8bb927724cf69ba34013b221114ab9456c3`.
The reference's brand color is adapted to LeadFinder green.
No calendar, HR, account, or demo-data features are included.

MIT License

Copyright (c) 2026 Kargul Studio

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


## Geist font

Geist is served locally from `leadfinder/static/fonts/Geist-Variable.ttf`.
Source: https://github.com/google/fonts/tree/main/ofl/geist
License: SIL Open Font License 1.1, included in `leadfinder/static/fonts/OFL.txt`.

## WhatsApp integration dependencies

The optional native bridge uses whatsapp-web.js, Puppeteer and qrcode, installed
separately with npm. Their upstream licenses are retained in their packages:

- whatsapp-web.js: Apache-2.0, https://github.com/wwebjs/whatsapp-web.js
- Puppeteer: Apache-2.0, https://github.com/puppeteer/puppeteer
- qrcode: MIT, https://github.com/soldair/node-qrcode

No dependency authentication/session data is part of the source distribution.


## AI credential encryption

API credentials are encrypted locally using [cryptography](https://cryptography.io/), distributed under Apache-2.0 or BSD-3-Clause. The dependency is installed separately; no API keys or provider SDK sources are bundled in the repository.


## Beautiful UI components

Native adaptations of ChatComposer, PromptBar, LoadingState, SearchList and RecommendationCard from [Beautiful UI](https://www.beautifului.dev/) are used in the campaign assistant and provider settings. Copyright (c) 2026 Shane Levine, MIT. Full notice: `leadfinder/static/licenses/beautiful-ui-LICENSE.txt`. Source and adaptation notes: `docs/BEAUTIFUL_UI.md`.
