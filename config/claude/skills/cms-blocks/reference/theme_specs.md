# Theme Specifications

Quick reference for the 16 industry-specific themes. Each theme has unique structural layouts, not just color variations.

**Full specifications**: `docs/blocks/THEME_SPECIFICATIONS.md`

## Theme Overview

| Theme | Industry | Animation | Key Differentiator |
|-------|----------|-----------|-------------------|
| elegance | High-end Luxury | Very Low (900-1200ms) | Art Deco geometric frames, diamond accents |
| elevate | General | Medium (400-500ms) | Professional default |
| vitalis | Wellness | Low (600-800ms) | S-curve paths, organic shapes |
| momentum | Sports/Fitness | High (200-300ms) | 45° diagonals, motion lines |
| pure-balance | Spa/Luxury | Low (800-1000ms) | 2-3x whitespace, symmetry |
| solid-craft | Construction | Low (500ms) | Blueprint grid, technical |
| growth-path | Coaching/Education | Medium (400ms) | Stepped progression, badges |
| clear-signal | Communication | Medium (500ms) | Node network, connections |
| bold-studio | Fashion/Retail | High (300ms) | Editorial, full-width imagery |
| trustline | Finance | Low (400ms) | Data visualization, graphs |
| vital-care | Healthcare | Low (500-600ms) | Patient journey, accessible |
| taste-mood | Hospitality | Medium (400ms) | Recipe card style, warm |
| urban-living | Real Estate | Medium (500ms) | Architectural blueprint |
| smooth-commerce | E-commerce | High (250ms) | Product carousel, cards |
| professional-edge | B2B Services | Low (400-500ms) | Flowchart, decision points |
| aperol-spritz | Lifestyle | Medium (400-500ms) | Scrapbook, overlapping |
| surfking | Extreme Sports | High (200ms) | Bold, energetic |

## Animation Energy Levels

### High Energy (200-300ms)
- **Themes**: momentum, bold-studio, smooth-commerce, surfking
- **Easing**: `cubic-bezier(0.68, -0.55, 0.265, 1.55)` (bounce)
- **Style**: Fast, snappy, dynamic

### Medium Energy (400-500ms)
- **Themes**: aperol-spritz, clear-signal, growth-path, taste-mood, urban-living, elevate
- **Easing**: `cubic-bezier(0.25, 0.46, 0.45, 0.94)` (smooth)
- **Style**: Balanced, engaging

### Low Energy (500-1000ms)
- **Themes**: vitalis, pure-balance, solid-craft, trustline, vital-care, professional-edge
- **Easing**: `cubic-bezier(0.4, 0, 0.2, 1)` (elegant)
- **Style**: Slow, refined, sophisticated

### Very Low Energy (900-1200ms) - Elegance
- **Themes**: elegance
- **Easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (theatrical)
- **Style**: Deliberate, theatrical reveals, dramatic pauses

## Color Patterns by Theme

### Dark Backgrounds
```blade
{{-- momentum, bold-studio, solid-craft, urban-living --}}
style="background: var(--tenant-primary-950);"
style="color: var(--tenant-primary-50);"
```

### Light Backgrounds
```blade
{{-- vitalis, pure-balance, trustline, vital-care, professional-edge --}}
style="background: linear-gradient(180deg, var(--tenant-primary-50), white);"
style="color: var(--tenant-primary-900);"
```

### Gradient Backgrounds
```blade
{{-- growth-path, clear-signal --}}
style="background: linear-gradient(to top, var(--tenant-primary-100), var(--tenant-secondary-50));"
```

### Warm Backgrounds
```blade
{{-- taste-mood --}}
style="background: linear-gradient(180deg, var(--tenant-secondary-50), white);"
```

## Theme-Specific Patterns

### Momentum (Sports)
- Diagonal cuts at 30-45°
- Motion blur effects
- High contrast
- Bold, condensed typography

```blade
<div style="transform: skewY(-3deg);">
<div style="background: linear-gradient(45deg, var(--tenant-primary-600), var(--tenant-secondary-500));">
```

### Pure Balance (Luxury)
- Perfect symmetry
- 2-3x normal whitespace
- Thin, elegant lines
- Slow fade animations

```blade
<div class="text-center py-24 lg:py-32">
<div style="border: 1px solid var(--tenant-primary-200);">
```

### Solid Craft (Construction)
- Blueprint grid background
- Technical precision
- Monospace for measurements
- Sequential build animations

```blade
<div style="background-image: linear-gradient(var(--tenant-primary-800) 1px, transparent 1px);">
<span class="font-mono">01</span>
```

### Vital Care (Healthcare)
- Stage-based progression
- High accessibility
- Calming colors
- Heartbeat-style animations

```blade
<div class="text-lg" style="color: var(--tenant-primary-900);">  {{-- Accessible font size --}}
```

### Taste & Mood (Hospitality)
- Recipe card aesthetic
- Warm color palette
- Handwritten-style elements
- Course metaphors

```blade
<div style="background: color-mix(in srgb, var(--tenant-secondary-500) 10%, transparent);">
```

## Structural Differentiators

| Theme | Layout Style | Special Elements |
|-------|--------------|-----------------|
| vitalis | Flowing S-curve | Botanical decorations |
| momentum | Diagonal ascending | Motion lines |
| pure-balance | Centered symmetry | Minimal decorations |
| solid-craft | Blueprint grid | Technical annotations |
| growth-path | Stepped stairs | Achievement badges |
| clear-signal | Node network | Connection lines |
| bold-studio | Editorial magazine | Full-width images |
| trustline | Data visualization | Graph elements |
| smooth-commerce | Product carousel | Card stacks |
| professional-edge | Flowchart | Decision diamonds |

## Typography by Theme

### Bold/Heavy (700-900)
- momentum, solid-craft, bold-studio

### Medium (500-600)
- elevate, growth-path, clear-signal, smooth-commerce, professional-edge

### Light (300-400)
- vitalis, pure-balance, trustline, vital-care

## Implementation Checklist

When creating a new theme view:

- [ ] Match the specified animation energy level
- [ ] Use correct color patterns (dark/light/gradient)
- [ ] Implement the structural differentiator
- [ ] Use appropriate typography weight
- [ ] Follow industry-specific visual metaphor
- [ ] Use only tenant CSS variables
- [ ] No hardcoded text or colors
- [ ] Responsive design maintained
- [ ] Accessibility for vital-care theme

## Related Files

- Full specs: `docs/blocks/THEME_SPECIFICATIONS.md`
- Theme views: `resources/views/blocks/{block}/{theme}.blade.php`
- Headers: `resources/views/components/site/header/{theme}.blade.php`
- Footers: `resources/views/components/site/footer/{theme}.blade.php`
