# Downloading from Royal Road with FlareSolverr

Royal Road sits behind a Cloudflare bot challenge, and plain downloads from it fail with HTTP 403. FanFicFare (the library
behind the Fanfic Site Downloader plugin) can send its requests through
[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr), a small server you run yourself that opens a real browser,
waits for the challenge to be solved, and hands the page back. These steps are for your own reading copies of stories
you can read for free in a browser.

**Status of this guide:** the plugin-side settings come from FanFicFare's own documentation and source, and the FlareSolverr
commands from FlareSolverr's README. I could not run FlareSolverr or reach Royal Road from the build environment, so none of
it has been tried end to end. FlareSolverr's own README says its automatic captcha solvers do not currently work, so a
challenge that needs a person to click may still fail.

## 1. Run FlareSolverr

You need it running on the same computer as Calibre (or another machine you control).

**Docker (recommended by FlareSolverr).** Install Docker, then run:

```bash
docker run -d \
  --name=flaresolverr \
  -p 127.0.0.1:8191:8191 \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest
```

On Windows Command Prompt or PowerShell, put it on one line:

```cmd
docker run -d --name=flaresolverr -p 127.0.0.1:8191:8191 -e LOG_LEVEL=info --restart unless-stopped ghcr.io/flaresolverr/flaresolverr:latest
```

`127.0.0.1:` in the port setting keeps it reachable only from your own computer. FlareSolverr has no password, so do not
publish port 8191 to a network you do not trust.

**Without Docker (Windows or Linux, x64 only).** Download the FlareSolverr executable from its
[releases page](https://github.com/FlareSolverr/FlareSolverr/releases) and run it. It needs Chrome (or Chromium on Linux)
installed. Other CPU types should use the Docker image.

FlareSolverr starts a new browser for each request, so it uses a fair amount of memory.

## 2. Check that it answers

```bash
curl -L -X POST 'http://localhost:8191/v1' \
  -H 'Content-Type: application/json' \
  --data-raw '{"cmd": "request.get", "url": "https://www.royalroad.com/fiction/21220", "maxTimeout": 60000}'
```

(The **Test** buttons in this window do the same checks for you.) A working setup returns JSON containing `"status": "ok"` and, inside `solution`, a `status` of 200 and the page HTML. If it
returns an error, fix that first (see Troubleshooting); the plugin will fail in the same way. Start it with
`-e LOG_LEVEL=debug` to see more.

## 3. Tell the plugin to use it

In the plugin's download window, the **Enable for Royal Road** button (in this guide's window) adds the lines below to
**Advanced settings** for you, without touching anything else already there. To do it by hand instead, paste this into
**Advanced settings**:

```ini
[www.royalroad.com]
use_flaresolverr_proxy:true
```

That is enough when FlareSolverr runs on the same computer with its default port. The defaults FanFicFare uses are:

```ini
flaresolverr_proxy_address:localhost
flaresolverr_proxy_port:8191
flaresolverr_proxy_protocol:http
flaresolverr_proxy_timeout:59000
```

Add any of those lines under `[www.royalroad.com]` only if yours differ (for example, FlareSolverr on another machine of yours).
The timeout is in milliseconds, and FanFicFare advises keeping it smaller than its own `connect_timeout`.

Enable it for Royal Road only, as above, rather than under `[defaults]`: FanFicFare recommends per-site use, and with
FlareSolverr 2 or later it turns off image downloading for the sites it is used with.

## 4. Download

Make sure FlareSolverr is running, then paste a story address such as `https://www.royalroad.com/fiction/21220` into the
dialog. Royal Road stories can have hundreds of chapters, and each chapter is a separate request through a browser, so a
long story takes a long time. To try it first, add a chapter range to the address, for example
`https://www.royalroad.com/fiction/21220[1-3]`.

## Troubleshooting

| Message | What it usually means |
| --- | --- |
| `Connection to flaresolverr proxy server failed. Is flaresolverr started?` | Nothing is listening at the configured address and port. Start it, and run the check in step 2. |
| `Flaresolverr says: ...` | FlareSolverr reached Royal Road but could not get through; the text after it is FlareSolverr's reason. Update the image (`docker pull`, then recreate the container) and try again. |
| Timeouts | Raise `flaresolverr_proxy_timeout` (and `connect_timeout` above it), and check the machine has free memory. |
| Still `403` / "bot challenge" | FlareSolverr is not being used. Check the section name is exactly `[www.royalroad.com]`, and that the settings were saved by pressing OK. |
| Challenge needs a click | FlareSolverr's captcha solvers do not currently work, so this can fail whatever you configure. Use the browser-cache method below. |

## Alternative: browser cache

If FlareSolverr cannot get through, FanFicFare can instead read pages your own browser has already loaded. Open the story and its
chapters in Chrome or Firefox, then add under `[defaults]` (path adjusted to your system, examples are in FanFicFare's
`defaults.ini`):

```ini
[defaults]
browser_cache_path:/home/you/.cache/google-chrome/Default/Cache/Cache_Data

[www.royalroad.com]
use_browser_cache:true
```

By default only pages fetched within the last 4 hours (`browser_cache_age_limit`) are used. This path is also untested here.
