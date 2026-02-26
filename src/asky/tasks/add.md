another problem shortlisting is disabled yeah the
shortlisting is affects like it's it's currently it's only defined under research configuration but it it affects also non-research mode this is yeah a mistake it should become
config should be configurable general yeah also for normal mode and research mode separately

The other problem is, when shortlisting is disabled for research, it's also disabled for non-research code. We don't have a shortlist configuration for general normal queries. We have per model shortlisting, all right, but not for general queries.

Currently, our Playwright plugin fails to detect some captchas, and I can see for a moment the page asks to prove I am a human, but it disappears in a second. And then, yeah, actually, there is code for that, but it's failing, it's not good enough apparently. And another problem with Playwright implementation: in some pages, it waits quite a lot, and I can see page content is there. There is only just a cookie banner. So, yeah, sometimes there will be cookie approval banners, but in some pages, that doesn't make it wait, but in some other pages, I can see the block of the article behind the cookie banner, which partially hides. So I'm not sure what it waits in those situations. Like, I'm not expecting you to completely be able to fix this, but at least we should have better debugging to investigate further.

│ │ ◠ ❞ │ k Tools : web_search: 0 | get_url_content: 0 | get_url_details: 0 | list_dir: 0 | grep_search: 0 | save_memory: 0 | Turns: 0/6 │
