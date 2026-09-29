# Terra II: polish and art pass

Kind: dated implementation/measurement record. Date: 2026-09-06.
Source additions: dd3a3e6, 1e7c170, 1c1d7c9 and 6bb4c9b (2026-09-06).
Extracted without reconciling historical claims on 2026-09-29 from
[TERRA2.md](2026-09-04-TERRA2.md). No historical checks were rerun.

## Polish, batch one

Motion arrives instead of stopping: an integer easing set (`easeOut`,
`easeIn`, `easeInOut`, a `backOut` that overshoots and settles) runs the
summon pop, the death shrink, the slides, the recoil, the damage tags
and sparks, the banner's scale-in, the card lift and the panel's
brighten-in.  Visual state chases the model: the cursor is a ring of
four amber strips that glides a third of the way to its slot every tick
and breathes; a hover clock (`hovT`) times the lifted card and the panel.
A summon is a card slab flying from the hand's edge (the enemy's from
beyond its HQ) to the slot on a small arc, shrinking and turning, the
unit popping up as it lands.

The look is one palette declared at the top of the program: a dusk sky
and ground, two desaturated factions with a light of each, amber as the
single accent, a danger red, and the 2D layer's ink and paper.  The
walker's lights list takes a second entry, the sky -- (fog and clear
colour, ambient tint) -- and the shader now mixes a cool ambient with
the warm sun and fogs by distance toward the sky, so the far compound
settles into the horizon; a backdrop wall and a ground rim carry the
gradient.  Every unit stands on a flat shadow ellipse; tiles carry a
light edge strip so the board reads as a board.

## Polish, batch two

Things fade now: the walker's instance colour carries an alpha
((r, g, b, a) beside the plain triple), and each mesh draws its opaque
instances first, then the translucent ones blended, depth-tested but
not depth-written, sorted far to near -- so smoke thins out, sparks and
damage tags dissolve, a destroyed unit fades as it shrinks, and the
scorch mark it leaves fades over twenty seconds.  The enemy's turn plays
under a veil, a translucent sheet over the board fading in and out over
400 ms, with a 260 ms beat between its actions so they read as decisions
rather than a burst.  The supply figure in the bar counts up and down one
a tick and stays amber while it moves.  Repeated cues vary in pitch by a
few percent from the clock, so four rifle cracks are four cracks.  On the
title screen the camera drifts slowly over the board until ENTER.

## Polish, batch three

Aiming shows its options: every slot the attacker can hit wears a
breathing red ring, the HQ a wider one and a pulse on the compound
itself, the amber cursor ring on the one being aimed at.  The hand
closes the gap a played card leaves (its ghost shrinks in place over 200
ms) and opens one for a dealt card (it grows in).  A struck HQ collects
craters in front of its compound.  The hovered unit's label brightens and
grows a step.  The title is a framed logo in the 2D layer over the
drifting board -- the name, a line about the two factions, a blinking
prompt, the keys -- with the bar and the hand hidden until the game
begins.

## The art pass

The look was cells and slabs; a modern surface wants type and rounded
glass.  The walker gained a real face -- DejaVu Sans Bold as a signed-
distance-field atlas and a text pass (docs/2026-09-05-UI2D.md) -- and scene2d the
treatments to go with it (`Fs`, `Round`, `Shadow`, `Bga`, `Center`,
`Mid`).  The layer now runs at 960 x 600, one virtual px per window px,
and everything on it was redrawn: a glass status bar with chips (TURN,
YOU, ENEMY, ENV) and captioned figures; the message in the face; the
banner in a glass pill that grows in with the back-out ease; the unit
panel as a rounded glass card with a header band in the unit's kind
colour, stat chips for ATK/GEN and HP, and the keys that apply as key
caps; the hand as 124 x 150 rounded, shadowed cards -- a kind band with
the name and an amber cost badge (red when you cannot afford it), the
kind in small caps, big ATK/DEF figures -- the cursor's card lifted, lit
and rimmed amber, the ghost and the dealt card keeping their tweens.
The title is a glass card with the name at 64 px.  On the board the unit
labels, the HQ figure, the ambush "?" and the damage tags are text
entities standing over their units instead of glyph cells.

