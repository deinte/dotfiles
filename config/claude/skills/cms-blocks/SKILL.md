---
name: cms-blocks
description: Create, modify, and validate CMS content blocks with proper theme layouts and tenant color system
tools:
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - Bash
---

# CMS Content Blocks Skill

Guide for creating, modifying, and validating content blocks in the Laravel multi-tenant CMS.

## Critical Rules

### MUST DO

- [ ] **Search existing blocks** before creating new (`ls -la app/Blocks/`)
- [ ] **Use `LinkInput`** for all links (never TextInput for URLs)
- [ ] **Use `ImagePicker`** for all images (never FileUpload)
- [ ] **Use `PaletteColorPicker`** for colors (shows brand palette swatches)
- [ ] **Use `<x-link>`** component to render links in views
- [ ] **Use tenant CSS variables** (`var(--tenant-primary-500)`)
- [ ] **All visible text from `$content` fields** - no hardcoded strings
- [ ] **Run `php artisan blocks:validate`** after changes
- [ ] **Add Umami analytics** to interactive elements
- [ ] **Use traits**: `HasLayoutFieldCapabilities`, `HasThemeConfiguration`
- [ ] **Use `HasBackgroundOptions`** trait for blocks needing background customization

### NEVER DO

- [ ] Hardcode text strings in views ("Welcome", "Read More")
- [ ] Hardcode colors (`#3b82f6`, `amber-500`, `blue-600`)
- [ ] Use translation calls (`__()`) for block content in views
- [ ] Create duplicate blocks - add layout variant instead
- [ ] Skip validation before committing
- [ ] Use `@media` queries in inline styles
- [ ] Use nested Blade comments (`{{-- ... {{-- ... --}} ... --}}` - inner closes outer)

## Quick Validation

```bash
# Validate all blocks
php artisan blocks:validate

# Validate specific block
php artisan blocks:validate --block=hero

# Validate specific theme
php artisan blocks:validate --block=hero --theme=elevate

# Check undefined content fields
php artisan blocks:validate --check-fields

# Check for nested Blade comments (causes parse errors)
grep -rn '{{--.*{{--' resources/views/blocks/ resources/views/components/

# Test view renders without errors
php artisan tinker --execute="view('blocks.hero.elevate', ['content' => []])->render();"
```

## Task Workflows

### Creating a New Block

1. **Search existing blocks first**:
   ```bash
   ls -la app/Blocks/
   grep -r "similar-feature" app/Blocks/
   ```

2. **Decision**: If 80%+ similar to existing block, add layout variant instead

3. **Create block class** at `app/Blocks/YourBlock.php`:
   - Extend `Block`
   - Use traits: `HasLayoutFieldCapabilities`, `HasThemeConfiguration`
   - Implement required methods
   - See reference: `reference/block_structure.md`

4. **Create view** at `resources/views/blocks/your-block/{theme}.blade.php`:
   - Extract content at top of file
   - Use `<x-block-section>` wrapper
   - Use tenant CSS variables
   - See reference: `reference/view_patterns.md`

5. **Add translations** to `lang/nl/tenant-blocks.php`

6. **Validate**: `php artisan blocks:validate --block=your-block`

### Adding a Theme/Layout Variant

1. **Add layout to block class**:
   ```php
   public static function getLayouts(): array
   {
       return [
           'existing-theme' => __('tenant-blocks.block.layouts.existing'),
           'new-theme' => __('tenant-blocks.block.layouts.new'),  // Add
       ];
   }
   ```

2. **Create view**: `resources/views/blocks/{block}/{new-theme}.blade.php`

3. **Follow theme specification** from `reference/theme_specs.md`

4. **Validate**: `php artisan blocks:validate --block={block} --theme={new-theme}`

### Fixing Validation Errors

See `reference/validation_rules.md` for specific error fixes:
- `hardcoded_html_text` → Use `$content['field']`
- `translation_call` → Use `$content['field']`
- `hardcoded_hex_color` → Use `var(--tenant-primary-*)`
- `inline_media_query` → Use `<style>` block
- `undefined_field` → Add to `getDefaultContent()`

## Block Categories

| Category | Examples | Icon Prefix |
|----------|----------|-------------|
| Layout | Hero, Banner, CTA | `heroicon-o-rectangle-*` |
| Content | TextWithMedia, FAQ, Team | `heroicon-o-document-*` |
| Media | Gallery, Video | `heroicon-o-photo` |
| Forms | ContactForm | `heroicon-o-envelope` |
| Commerce | Pricing, FeaturedProduct | `heroicon-o-shopping-*` |

## Available Themes (16)

| Theme | Industry | Animation Energy |
|-------|----------|------------------|
| elevate | General | Medium |
| vitalis | Wellness | Low |
| momentum | Sports/Fitness | High |
| pure-balance | Spa/Luxury | Low |
| solid-craft | Construction | Low |
| growth-path | Coaching/Education | Medium |
| clear-signal | Communication | Medium |
| bold-studio | Fashion/Retail | High |
| trustline | Finance | Low |
| vital-care | Healthcare | Low |
| taste-mood | Hospitality | Medium |
| urban-living | Real Estate | Medium |
| smooth-commerce | E-commerce | High |
| professional-edge | B2B Services | Low |

## Pre-Commit Checklist

```bash
# 1. Format code
./vendor/bin/pint

# 2. Static analysis
composer analyse

# 3. Validate blocks
php artisan blocks:validate

# 4. Run relevant tests
php artisan test tests/Feature/BlockSchemaRenderingTest.php
php artisan test tests/Feature/ValidateBlockViewsTest.php
```

## Reference Files

- `reference/block_structure.md` - Block class template with traits
- `reference/color_system.md` - Tenant CSS variables and brand palette
- `reference/view_patterns.md` - Blade patterns and helpers
- `reference/validation_rules.md` - Validation errors and fixes
- `reference/components.md` - LinkInput, ImagePicker, PaletteColorPicker, HasBackgroundOptions
- `reference/theme_specs.md` - 16 theme specifications

## Project Documentation

- `docs/COMPONENT_CREATION_GUIDELINES.md` - Full component guide
- `docs/blocks/THEME_SPECIFICATIONS.md` - Detailed theme specs
- `docs/blocks/VALIDATION.md` - Validation rules
