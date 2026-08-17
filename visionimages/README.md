# visionimages

Images for the vision board on the site's root `index.html`.

The board has nine slots and fills them left to right, top to bottom, in the
order listed in the `IMAGES` array near the bottom of `index.html`:

```
01  02  03
04  05  06
07  08  09
```

To add one: drop the file in this folder and add a line to that array —

```js
{ file: "IMG_6167.jpg", alt: "Short description of the image." },
```

Filenames can be anything (straight off a phone is fine). Any slot without an
entry shows a numbered placeholder tile, so a partial set looks intentional.
The `alt` text is read aloud by screen readers and shown if an image fails to
load; a short plain description is all it needs.

Images are shown whole rather than cropped to fill (`object-fit: contain`),
since several carry captions right at the edge that a crop would cut off. Any
shape works. Keep files under ~500 KB each so the board loads fast on a phone.
