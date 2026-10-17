import type { CSSProperties } from 'react';
import { FRAME, SHEET_COLS, sheetUrl } from '../sprites';

interface Props {
  sprite?: string;
  size?: number;
  dead?: boolean;
  title?: string;
  /** Facing row of the sheet (0 = south). */
  row?: number;
}

// The character occupies roughly the 18x18 centre of each 32x32 frame; crop to it.
const CROP_X = 7;
const CROP_Y = 6;
const CROP = 18;

/** A character portrait cut from its sprite sheet with CSS (no canvas needed). */
export function Avatar({ sprite = 'human-worker-red', size = 28, dead = false, title, row = 0 }: Props) {
  const scale = size / CROP;
  const style: CSSProperties = {
    width: size,
    height: size,
    flexShrink: 0,
    backgroundImage: `url(${sheetUrl(sprite)})`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${SHEET_COLS * FRAME * scale}px ${8 * FRAME * scale}px`,
    backgroundPosition: `${-CROP_X * scale}px ${-(row * FRAME + CROP_Y) * scale}px`,
    imageRendering: 'pixelated',
    filter: dead ? 'grayscale(1) opacity(0.55)' : undefined,
    borderRadius: 6,
    backgroundColor: 'var(--mantine-color-default-hover)',
  };
  return <div style={style} title={title} aria-label={title} role={title ? 'img' : undefined} />;
}
