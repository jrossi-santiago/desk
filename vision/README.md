# vision

Images for the vision board on the site's root `index.html`.

Name them `01` through `09` — they fill the 3x3 grid in that order:

```
01  02  03
04  05  06
07  08  09
```

`.jpg`, `.jpeg`, `.png` and `.webp` all work; the page tries each in turn, so
`01.png` and `02.jpg` can sit side by side. Any number with no matching file
shows a numbered placeholder tile instead, so a partial set is fine.

Images are cropped to fill their tile (`object-fit: cover`) — square-ish crops
look best on desktop, and the mobile stack shows them at 4:5. Keep files under
~500 KB each so the board loads quickly on a phone.
