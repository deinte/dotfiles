# Tenant Color System

Tenant colors are configured per-tenant and exposed as CSS custom properties. **Never hardcode brand colors.**

## Brand Palette (2-4 Colors)

Tenants can define a brand palette with up to 4 colors:
- **Primary** - Main brand color
- **Secondary** - Accent color
- **Accent 1** - Optional additional color
- **Accent 2** - Optional additional color

### Using PaletteColorPicker

In block schemas, use `PaletteColorPicker` instead of standard `ColorPicker` to show brand swatches:

```php
use App\Forms\Components\PaletteColorPicker;

// Shows color picker with brand palette swatches
PaletteColorPicker::make('background_color')
    ->label(__('tenant-blocks.your_block.fields.background_color'));

// Hide palette for fully custom colors
PaletteColorPicker::make('custom_color')
    ->hidePalette();
```

### Using BrandPaletteService

For programmatic access to the palette:

```php
use App\Services\BrandPaletteService;

// Get all palette colors (2-4 hex values)
$colors = BrandPaletteService::getActivePalette();
// ['#3b82f6', '#64748b', '#10b981', '#f59e0b']

// Check if enough colors for palette shaking
$canShake = BrandPaletteService::hasMultipleColors(); // true if 3+ colors

// Randomly pick 2 different colors from palette
[$primary, $secondary] = BrandPaletteService::shake($colors);

// Get palette with labels for UI
$paletteWithLabels = BrandPaletteService::getPaletteWithLabels();
// [['color' => '#3b82f6', 'label' => 'Primair'], ...]
```

---

## Available CSS Variables

### Primary Colors (Brand)

```css
var(--tenant-primary-50)   /* Lightest */
var(--tenant-primary-100)
var(--tenant-primary-200)
var(--tenant-primary-300)
var(--tenant-primary-400)
var(--tenant-primary-500)  /* Base */
var(--tenant-primary-600)
var(--tenant-primary-700)
var(--tenant-primary-800)
var(--tenant-primary-900)
var(--tenant-primary-950)  /* Darkest */
```

### Secondary Colors (Accent)

```css
var(--tenant-secondary-50)   /* Lightest */
var(--tenant-secondary-100)
var(--tenant-secondary-200)
var(--tenant-secondary-300)
var(--tenant-secondary-400)
var(--tenant-secondary-500)  /* Base */
var(--tenant-secondary-600)
var(--tenant-secondary-700)
var(--tenant-secondary-800)
var(--tenant-secondary-900)
var(--tenant-secondary-950)  /* Darkest */
```

## Usage Patterns

### Backgrounds

```blade
{{-- Light backgrounds --}}
<section style="background-color: var(--tenant-primary-50);">

{{-- Dark backgrounds --}}
<section style="background-color: var(--tenant-primary-900);">

{{-- Gradients --}}
<div style="background: linear-gradient(135deg, var(--tenant-primary-500), var(--tenant-secondary-500));">

{{-- Vertical gradient --}}
<div style="background: linear-gradient(to bottom, var(--tenant-primary-100), white);">
```

### Text

```blade
{{-- Dark text on light bg --}}
<h1 style="color: var(--tenant-primary-900);">

{{-- Light text on dark bg --}}
<p style="color: var(--tenant-primary-50);">

{{-- Muted text --}}
<span style="color: var(--tenant-primary-600);">
```

### Borders

```blade
{{-- Subtle border --}}
<div style="border: 1px solid var(--tenant-primary-200);">

{{-- Accent border --}}
<div style="border-left: 4px solid var(--tenant-secondary-500);">
```

### Transparency with color-mix()

```blade
{{-- 20% opacity background --}}
<div style="background-color: color-mix(in srgb, var(--tenant-primary-500) 20%, transparent);">

{{-- 50% opacity border --}}
<div style="border-color: color-mix(in srgb, var(--tenant-primary-50) 50%, transparent);">

{{-- Soft shadow --}}
<div style="box-shadow: 0 4px 20px color-mix(in srgb, var(--tenant-primary-500) 15%, transparent);">
```

### Buttons

```blade
{{-- Primary button --}}
<button style="background-color: var(--tenant-primary-500); color: white;">

{{-- Secondary button --}}
<button style="background-color: var(--tenant-secondary-500); color: white;">

{{-- Outline button --}}
<button style="border: 2px solid var(--tenant-primary-500); color: var(--tenant-primary-500);">

{{-- Ghost button --}}
<button style="background-color: color-mix(in srgb, var(--tenant-primary-500) 10%, transparent); color: var(--tenant-primary-600);">
```

## Shade Usage Guide

| Shade | Use Case |
|-------|----------|
| 50-100 | Light backgrounds, hover states |
| 200-300 | Borders, dividers, disabled states |
| 400-500 | Primary actions, buttons, links |
| 600-700 | Hover states, emphasis text |
| 800-950 | Dark backgrounds, heading text |

## WRONG vs RIGHT

### Hardcoded Colors (WRONG)

```blade
{{-- WRONG - Hardcoded hex --}}
<div style="background: #3b82f6;">

{{-- WRONG - Hardcoded Tailwind color --}}
<span class="text-amber-500">

{{-- WRONG - Hardcoded RGB --}}
<div style="color: rgb(59, 130, 246);">
```

### Tenant Colors (RIGHT)

```blade
{{-- RIGHT - CSS variable --}}
<div style="background: var(--tenant-primary-500);">

{{-- RIGHT - Dynamic --}}
<span style="color: var(--tenant-secondary-500);">

{{-- RIGHT - With transparency --}}
<div style="background: color-mix(in srgb, var(--tenant-primary-500) 20%, transparent);">
```

## Safe Neutral Colors

These colors are OK to hardcode as they're not brand-specific:

```blade
{{-- Grays for neutral elements --}}
<div class="bg-gray-100 text-gray-900">
<div class="border-slate-200">

{{-- Pure white/black --}}
<div class="bg-white text-black">

{{-- Status colors --}}
<span class="text-red-600">Error</span>
<span class="text-green-600">Success</span>
<span class="text-amber-600">Warning</span>

{{-- Transparent --}}
<div class="bg-transparent">
```

## Tailwind Classes (When Available)

The tenant colors are also available as Tailwind utilities:

```blade
{{-- Background --}}
<div class="bg-primary-500 bg-secondary-100">

{{-- Text --}}
<span class="text-primary-600 text-secondary-900">

{{-- Border --}}
<div class="border-primary-200">

{{-- Hover --}}
<button class="bg-primary-500 hover:bg-primary-600">
```

## Theme-Specific Overrides

For blocks using `HasThemeConfiguration`, use the `block_theme()` helper:

```blade
@php
$theme = block_theme($content, $layout, \App\Blocks\HeroBlock::class);
$overlayColor = $theme->color('overlay_gradient_start');
@endphp

<div style="background: {{ $overlayColor }};">
```
