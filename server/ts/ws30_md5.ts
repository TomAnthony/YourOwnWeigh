/** RFC 1321 MD5, solely for the WS-30's existing device challenge protocol.
 * Portable across Worker and Node runtimes; never used for stored passwords.
 * Algorithm: https://www.rfc-editor.org/rfc/rfc1321#section-3
 */
const rotations = [7, 12, 17, 22, 5, 9, 14, 20, 4, 11, 16, 23, 6, 10, 15, 21];
const constants = Array.from({ length: 64 }, (_, i) =>
  Math.floor(2 ** 32 * Math.abs(Math.sin(i + 1))),
);

export function ws30MD5(value: string): string {
  const input = new TextEncoder().encode(value);
  const padded = new Uint8Array(Math.ceil((input.length + 9) / 64) * 64);
  padded.set(input);
  padded[input.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setBigUint64(padded.length - 8, BigInt(input.length) * 8n, true);
  const state = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476];
  for (let offset = 0; offset < padded.length; offset += 64) {
    let [a, b, c, d] = state;
    for (let i = 0; i < 64; i++) {
      let f: number;
      let word: number;
      if (i < 16) {
        f = (b & c) | (~b & d);
        word = i;
      } else if (i < 32) {
        f = (d & b) | (~d & c);
        word = (5 * i + 1) % 16;
      } else if (i < 48) {
        f = b ^ c ^ d;
        word = (3 * i + 5) % 16;
      } else {
        f = c ^ (b | ~d);
        word = (7 * i) % 16;
      }
      const shift = rotations[Math.floor(i / 16) * 4 + (i % 4)];
      const sum =
        (a + f + constants[i] + view.getUint32(offset + word * 4, true)) | 0;
      [a, b, c, d] = [
        d,
        (b + ((sum << shift) | (sum >>> (32 - shift)))) | 0,
        b,
        c,
      ];
    }
    for (const [i, word] of [a, b, c, d].entries())
      state[i] = (state[i] + word) >>> 0;
  }
  const output = new DataView(new ArrayBuffer(16));
  state.forEach((word, i) => output.setUint32(i * 4, word, true));
  return Array.from(new Uint8Array(output.buffer), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
