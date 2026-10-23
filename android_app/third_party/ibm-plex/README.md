# IBM Plex (fonts in app/src/main/res/font)

SIL Open Font License 1.1, see LICENSE.txt. Copyright IBM Corp.

Source: npm `@ibm/plex-sans@1.1.0` and `@ibm/plex-sans-condensed@1.1.0`, files
`fonts/complete/woff/IBMPlexSans-{Regular,Medium}.woff` and
`IBMPlexSansCondensed-Medium.woff`. Those packages ship only web fonts, so each
WOFF was unwrapped to its TrueType data with fontTools (`TTFont(f); flavor = None;
save`). That changes the container, not the font.

Plex's default figures are tabular: all ten digits have the same advance in
every bundled file, and there is no `tnum` feature to switch on.
