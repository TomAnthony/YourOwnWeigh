/* WBS13 v1311 startup drawing callback; compiled by patch_startup.py.
 *
 * The original callback draws WITHINGS, a separator and Body Smart. Keep its
 * screen lifecycle and refresh scheduling, replacing only the drawing. The
 * native-resolution face uses four-byte horizontal spans generated from the
 * vector design in startup_artwork.py. Reuse the stock 320x240 framebuffer and
 * palette, with no new framebuffer or persistent RAM.
 */
#if !defined(YOW_FACE_ADDRESS) || !defined(YOW_FACE_SPANS)
#error "Build with patch_startup.py to supply the appended face address"
#endif

__attribute__((section(".text.startup"), used))
void yow_startup_face(void) {
    const unsigned char *face = (const unsigned char *)YOW_FACE_ADDRESS;
    void (*clear)(unsigned) = (void *)0x0807406f;
    void (*rect)(int, int, int, int, unsigned) = (void *)0x08074087;

    /* Stock palette: 13 = black (0x000), 6 = white (0xfff). */
    clear(13);
    for (unsigned i = 0; i < YOW_FACE_SPANS; ++i) {
        const unsigned char *span = face + i * 4;
        /* Native one-pixel rows; palette 14 supplies the soft yellow cheeks. */
        rect(32 + span[1], 12 + span[0], 32 + span[2], 12 + span[0], span[3]);
    }
}
