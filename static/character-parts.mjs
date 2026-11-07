/* Character kit scene-graph helpers.
 * A GLB mesh containing multiple material primitives is loaded by Three.js as
 * a named GROUP with children (e.g. person_m -> person_m_0 / person_m_1).
 * Toggle the named root of each wearable, never just its leaf Mesh objects.
 *
 * Which parts are worn follows the game's character.gd set_look():
 *   - the dress carries its own legs and shoes, so no legs mesh goes under it
 *     (trouser tops under a skirt poke through when the legs bend);
 *   - the trench wears legs_coat, which has no trouser tops under the coat;
 *   - everything else wears the chosen bottoms: legs_m (trousers), legs_shorts or legs_jeans
 *     (Character Forge additions, like the T-shirt and tank top).
 * export_character.py applies the same rule; keep the two in step.
 */
export const CHARACTER_PARTS = Object.freeze([
  'person_m', 'person_f', 'legs_m', 'legs_coat',
  'outfit_suit', 'outfit_trench', 'outfit_shirt', 'outfit_dress',
  'hair_short', 'hair_long', 'hat', 'glasses',
  'outfit_tshirt', 'outfit_tank', 'legs_shorts', 'legs_jeans'
]);

export const OUTFITS = Object.freeze(['suit', 'trench', 'shirt', 'dress', 'tshirt', 'tank']);
export const BOTTOMS = Object.freeze({ trousers: 'legs_m', shorts: 'legs_shorts', jeans: 'legs_jeans' });

// Outfits that come with their own legs: the bottoms choice doesn't apply to them.
export const ownLegs = outfit => outfit === 'dress' || outfit === 'trench';

export function legsFor(outfit, bottoms = 'trousers') {
  if (outfit === 'dress') return null;
  if (outfit === 'trench') return 'legs_coat';
  return BOTTOMS[bottoms] || 'legs_m';
}

export function collectCharacterParts(root) {
  const parts = new Map();
  for (const name of CHARACTER_PARTS) {
    const node = root.getObjectByName(name);
    if (node) parts.set(name, node);
  }
  return parts;
}

function requiredParts(cfg) {
  const outfit = OUTFITS.includes(cfg.outfit) ? cfg.outfit : 'suit';
  const legs = legsFor(outfit, cfg.bottoms);
  return [cfg.body === 'f' ? 'person_f' : 'person_m', ...(legs ? [legs] : []), 'outfit_' + outfit];
}

export function desiredCharacterParts(cfg) {
  const selected = new Set(requiredParts(cfg));
  if (cfg.hair === 'short' || cfg.hair === 'long') selected.add('hair_' + cfg.hair);
  if (cfg.hat) selected.add('hat');
  if (cfg.glasses) selected.add('glasses');
  return selected;
}

export function applyCharacterParts(parts, cfg) {
  const selected = desiredCharacterParts(cfg);
  for (const [id, node] of parts) node.visible = selected.has(id);
  const missing = [...selected].filter(id => !parts.has(id));
  // A character is only valid if its mandatory anatomical pieces exist.
  const absent = requiredParts(cfg).filter(id => !parts.has(id));
  if (absent.length) throw new Error('Character geometry missing in loaded GLB: ' + absent.join(', '));
  return { selected: [...selected], missing, visible: [...selected].filter(id => parts.has(id)) };
}
