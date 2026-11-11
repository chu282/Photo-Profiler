# Photo Profiler: development and detailed guide

Run **Photo Profiler Setup 1.14.exe** in `dist` to install for your Windows account. It creates a Start menu shortcut and an uninstaller; a desktop shortcut is optional. No Python installation is required. For portable use, copy the entire `dist\Photo Profiler` folder and run its **Photo Profiler.exe**; keep its `_internal` folder beside it.

The installed app now runs as a single process, without the extra background wrapper used in earlier releases. A second launch activates the existing copy of that installation. Updates request a normal close and save the current session before replacing files. A small installer helper clears stuck processes from older versions only when their executable path exactly matches the installation being updated; other applications and portable copies are left alone. Session data remains in the same location.

To run from source, use **Start Photo Profiler.cmd** with Python 3.10+. First launch installs two small libraries; subsequent use is offline.

1. Open **Folders**, add folders, click **Done**, and click **Scan**. Leave **Subfolders** checked if wanted.
2. Toggle the six graph checkboxes to show any combination. The four camera-setting graphs open in a compact 2×2 grid; orientation and aspect ratio are optional. Hover over bars for exact counts.
3. Choose **Distribution** for counts or **Over time** for capture date on the x-axis and the selected setting on the y-axis.
4. In the time view, optionally enable **Average** and set a trailing window in days. **Log scale** helps with wide shutter-speed or ISO ranges. Hover over points for details.

Right-click a histogram bar (including its top or side) to list the matching filenames and folders. The list uses the active outlier filter and focal-length mode, so its count matches the bar. Double-click a row or press Enter to open the photo in its default Windows app. Right-click a row for **Open**, **Show in folder** (selects the file in Explorer), **Open folder**, **Copy file name**, and **Copy file path**. Select rows and press Ctrl+C to copy filenames; Escape closes the list.

**Aspect ratio** uses a discrete bar graph with gaps between bars and centered ticks and labels, showing only ratios present in the scan. It shows the displayed width:height after EXIF rotation, using the actual exported image dimensions when available. Landscape 3:2 and portrait 2:3 are separate groups. Common ratios within 0.5% are grouped together so pixel rounding (for example, 4000×2667) does not create extra categories. Other ratios use reduced fractions or a compact decimal ratio. The time view shows ratio categories, without an average or logarithmic axis; outlier filtering leaves ratio categories intact. Right-click lists and image export work as for the other graphs. When you enable this graph on an older saved session, its missing aspect ratios are read in the background and cached automatically.

Bars over 1% display their percentage horizontally, centered over the projected 3D bar. Solid label backings cover any overlapping grid lines and tick marks. Numeric bars touch. Focal lengths use consecutive 5 mm histogram bins, including empty intervals. Labels show only the starting value: **20** means 20 mm up to (but not including) 25 mm. Ticks and labels align with the left edge. Other setting distributions retain the camera's exact reported settings. Orientation remains categorical. The 3D background has a solid back wall, side wall, and floor. Grid boundaries align with bar sides using the same depth projection as the bars.

Mouse wheel **up** zooms in horizontally around the pointer; **down** zooms out. Use the horizontal scrollbar to pan. Double-click a chart to reset its zoom. This works in both distribution and time views. Time plots label actual settings when they fit, otherwise use standard camera settings or round intervals. Dates follow calendar boundaries.

**35 mm equivalent** switches both focal-length views to the EXIF equivalent field when present. If absent, recognized camera models use recorded focal length × nominal sensor crop factor. Supported fallback models: Olympus E-M5 Mark II and E-M1 Mark II (2×), Canon EOS R10 and Rebel T2i/550D (1.6×), and EOS R6 and EOS 6D (1×). Explicit EXIF equivalents always take precedence. Unknown models or missing focal lengths remain missing. Sensor-based fallbacks do not account for later editing crops or camera crop modes when those are not described in EXIF. Unchecking restores actual focal length without rescanning.

**Common focal lengths only** switches focal length from a histogram to a discrete bar graph: separate bars with gaps, equally spaced category points, and ticks and labels centered beneath the projected bars. Photos group under the nearest of these values (in mm): 8, 10, 12, 14, 16, 18, 20, 24, 28, 35, 40, 50, 60, 70, 85, 100, 105, 135, 150, 180, 200, 250, 300, 400, 500, 600, 800. Exact halfway values go to the shorter focal length; values beyond the list go to the nearest endpoint. No photos are dropped. The graph shows common groups between the shortest and longest occupied groups, retaining empty groups between them. Outlier filtering happens before grouping. This uses either actual or 35 mm equivalent focal length according to the active toggle. The right-click file list follows the same grouping. Time plots keep measured values and use common focal lengths for axis labels. Uncheck to return to touching 5 mm histogram bins with left-edge ticks. This option is saved with the session.

After a scan and on close, the app saves results, folders, selected graphs, filters, and zoom settings in `%LOCALAPPDATA%\Photo Profiler\session.json`. Reopening restores the last histogram without scanning again. It stores metadata only. Rescan after adding or changing photos. Portable and installed versions share this cache; uninstalling leaves it intact.

**Export image** redraws the visible charts, text, and shapes at up to 3× display resolution (capped at 24 megapixels), including current selection and zoom. The PNG has 300 DPI print metadata and excludes the toolbar. The filename defaults to **Photo Profiler YYYY-MM-DD.png**, and the same local export date is printed in a small footer. This is a high-resolution render, not an enlarged screenshot.

**Hide outliers** filters each numeric graph independently using 1.5× the interquartile range. When that range is zero (for example, mostly one focal length), it trims only the outer 1% tails instead. It requires at least eight values, leaves orientation unchanged, and shows the hidden count in the graph title. Percentages and averages use the remaining photos; unchecking restores everything without rescanning.

No photos are modified or uploaded. Overlapping folders are scanned once. Stop keeps partial results. Files without EXIF are ignored; missing settings are omitted only from the relevant graph. Undated photos count in distributions but not time graphs. The status reports skipped files; **Details** lists read errors.

Orientation means landscape, portrait, or square after EXIF rotation. Focal length defaults to actual lens focal length. Shutter speed is measured in seconds. Time graphs use local capture dates from EXIF (original, digitized, then image date), never file modification dates.

Shutter speed prefers a valid EXIF ExposureTime from either metadata reader. ShutterSpeedValue (APEX) is used only when ExposureTime is unavailable or invalid. The recorded exposure is preserved, including nonstandard speeds; labels use full decimal numbers, never scientific notation. Rescan to apply metadata-reading fixes to a saved scan.

The optional line is a photo-weighted arithmetic mean over the current calendar day and preceding N−1 days, sampled daily. It uses the original values even with a logarithmic axis. Empty windows break the line. Orientation is categorical and has no average line. Histories longer than 4,000 days are sampled at up to 4,000 dates. Coincident points share a visible dot, but every photo contributes to counts and averages.

Reads JPEG, TIFF, PNG, WebP, HEIC/HEIF, JPEG XL, and many TIFF-based RAW formats (including DNG, NEF, CR2, and ARW). Format support depends on the libraries; unsupported or damaged files, including unsupported CR3 variants, appear under **Details**. Other file types are ignored. PNG/TIFF structural tags also count as EXIF when returned by the metadata libraries.

Metadata readers: [ExifRead](https://github.com/ianare/exif-py), [Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html).

Fallback sensor sources: [E-M5 II manual](https://download.omsystem.com/pages/inst/em5m2/manual_em5m2_ENU.pdf), [E-M1 II manual](https://download.omsystem.com/pages/inst/em1m2/manual_em1m2_ENU.pdf), [Canon RF-S/R10](https://files.canon-europe.com/files/webcontent/rf-lens-world/features/rf-lineup/index.html), [T2i/550D specifications](https://in.canon/en/support/6200065700), [EOS R6 manual](https://cam.start.canon/en/C004/manual/html/UG-03_Shooting-1_0040.html), [EOS 6D specifications](https://asia.canon/en/support/6200150900).

Run checks: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

To build the Windows installer from a checkout:

1. Create a virtual environment: `python -m venv .venv`.
2. Install build dependencies: `.venv\Scripts\python.exe -m pip install -r requirements-build.txt`.
3. Extract the [Inno Setup compiler](https://jrsoftware.org/isdl.php) in portable mode into `.temp\inno` so that `.temp\inno\ISCC.exe` exists.
4. Run `powershell -NoProfile -File .\build_installer.ps1`.

The installer is written to `dist`. The source repository excludes generated installers, virtual environments, saved sessions, and test exports.
