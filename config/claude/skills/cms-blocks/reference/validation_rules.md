# Block Validation Rules

The `php artisan blocks:validate` command enforces view quality rules.

## Command Usage

```bash
# Validate all block views
php artisan blocks:validate

# Validate specific block type
php artisan blocks:validate --block=hero

# Validate specific theme
php artisan blocks:validate --block=hero --theme=elevate

# Check for undefined content fields
php artisan blocks:validate --check-fields

# Output as JSON (for CI)
php artisan blocks:validate --json

# Only show errors
php artisan blocks:validate --errors-only
```

## Error Types and Fixes

### hardcoded_html_text

**What it catches**: Text strings directly in HTML tags.

**WRONG**:
```blade
<span>Welcome to our site</span>
<h2>Contact Us</h2>
<p>Ready to get started?</p>
<div class="badge">Premium</div>
```

**RIGHT**:
```blade
<span>{{ $content['welcome_text'] ?? '' }}</span>
<h2>{{ $heading }}</h2>
<p>{{ $content['cta_prompt'] ?? '' }}</p>
<div class="badge">{{ $content['badge_text'] ?? '' }}</div>
```

### translation_call

**What it catches**: `__()`, `trans()`, `@lang` calls in block views.

**WRONG**:
```blade
<span>{{ __('tenant-blocks.hero.cta') }}</span>
<button>@lang('tenant.buttons.submit')</button>
<p>{{ trans('messages.welcome') }}</p>
```

**RIGHT** - Use theme config or content fields:
```blade
{{-- Option 1: Content field (preferred) --}}
<span>{{ $content['cta_label'] ?? '' }}</span>

{{-- Option 2: Theme config (for layout-specific text) --}}
@php $theme = block_theme($content, $layout, \App\Blocks\HeroBlock::class); @endphp
<span>{{ $theme->text('cta_label') }}</span>
```

### hardcoded_hex_color

**What it catches**: Hex colors in inline styles.

**WRONG**:
```blade
<div style="background: #3b82f6;">
<span style="color: #fff;">
<div style="border-color: #64748b;">
```

**RIGHT**:
```blade
<div style="background: var(--tenant-primary-500);">
<span style="color: var(--tenant-primary-50);">
<div style="border-color: var(--tenant-secondary-300);">
```

### hardcoded_rgb_color

**What it catches**: RGB/RGBA colors in inline styles.

**WRONG**:
```blade
<div style="background: rgb(59, 130, 246);">
<div style="color: rgba(255,255,255,0.5);">
```

**RIGHT**:
```blade
<div style="background: var(--tenant-primary-500);">
<div style="color: color-mix(in srgb, var(--tenant-primary-50) 50%, transparent);">
```

### inline_media_query

**What it catches**: `@media` queries in inline style attributes.

**WRONG**:
```blade
<div style="width: 100%; @media (min-width: 768px) { width: 50%; }">
```

**RIGHT** - Use a `<style>` block:
```blade
<style>
    .responsive-element { width: 100%; }
    @media (min-width: 768px) { .responsive-element { width: 50%; } }
</style>
<div class="responsive-element">
```

**Or** - Use Tailwind classes:
```blade
<div class="w-full md:w-1/2">
```

### hardcoded_array

**What it catches**: Arrays with text strings.

**WRONG**:
```blade
@php
    $labels = ['Starter', 'Main Course', 'Dessert'];
    $features = ['Fast', 'Reliable', 'Secure'];
@endphp
```

**RIGHT** - From content field:
```blade
@php
    $labels = $content['item_labels'] ?? [];
    $features = $content['features'] ?? [];
@endphp
```

### undefined_field

**What it catches**: Using `$content['field']` where field isn't defined in `getDefaultContent()`.

**WRONG** - Using a field not in defaults:
```blade
<span>{{ $content['custom_field'] }}</span>
```

**RIGHT** - Add to block class:
```php
public static function getDefaultContent(): array
{
    return [
        'custom_field' => '',  // Add this
        // ... other fields
    ];
}
```

### nested_blade_comment (manual check)

**What it catches**: Nested Blade comments cause parse errors. Blade doesn't support nesting - the inner comment closes the outer one.

**WRONG**:
```blade
{{--
    Usage example:
    <x-component>
        {{-- Inner content --}}
    </x-component>
--}}
```

The inner `{{--` closes the outer comment, leaving `</x-component>` and `--}}` as actual code, causing syntax errors like "unexpected token endif".

**RIGHT** - Use plain text or HTML comments inside docblocks:
```blade
{{--
    Usage example:
    <x-component>
        ... inner content ...
    </x-component>
--}}
```

**Detection command**:
```bash
grep -rn '{{--.*{{--' resources/views/blocks/ resources/views/components/
```

## What's Allowed

| Pattern | Why OK |
|---------|--------|
| `{{ $content['title'] }}` | From content field |
| `{{ $content['x'] ?? 'default' }}` | Content with fallback |
| `{{ $heading }}` | Variable extracted from content |
| `{{ $theme->text('key') }}` | Theme configuration text |
| `var(--tenant-primary-500)` | Tenant CSS variable |
| `class="text-lg font-bold"` | Tailwind classes |
| `{{-- comment --}}` | Blade comment |
| `@if`, `@foreach` | Logic directives |
| `<style>` blocks | Raw CSS allowed inside |
| `@php` blocks | PHP code allowed |
| `color-mix(in srgb, var(--tenant-*) ...)` | CSS with tenant vars |

## Validation Checklist

Before committing block views:

- [ ] No hardcoded headings, titles, or labels
- [ ] No hardcoded stat values (15+, 98%, 500+)
- [ ] No hardcoded descriptions or paragraphs
- [ ] No hardcoded button/link text
- [ ] No hardcoded contact info (emails, phones)
- [ ] No placeholder text (info@example.com)
- [ ] No hardcoded trust badges or guarantees
- [ ] No hardcoded CTA prompts ("Ready to get started?")
- [ ] All hex/rgb colors replaced with CSS variables
- [ ] No `@media` in inline styles
- [ ] All content fields defined in `getDefaultContent()`
- [ ] No nested Blade comments (`grep -rn '{{--.*{{--' resources/views/`)
- [ ] Views render without errors (test with tinker)
- [ ] `php artisan blocks:validate` passes

## CI Integration

Add to your workflow:

```yaml
- name: Validate block views
  run: php artisan blocks:validate --errors-only
```

Or in pre-commit hook:

```bash
php artisan blocks:validate --errors-only || exit 1
```
