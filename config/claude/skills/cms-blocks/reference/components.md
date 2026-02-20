# Custom Form Components

Required custom components for block schemas and views.

## LinkInput

**Use for**: All links/buttons in block schemas. Never use TextInput for URLs.

**Location**: `App\Forms\Components\LinkInput`

### Schema Usage

```php
use App\Forms\Components\LinkInput;

// Single link
LinkInput::make('link'),

// In a repeater for buttons
Repeater::make('buttons')
    ->schema([
        TextInput::make('label')
            ->required()
            ->maxLength(50),

        LinkInput::make('link'),  // NOT TextInput!

        Select::make('style')
            ->options([
                'primary' => __('tenant-blocks.common.button_styles.primary'),
                'secondary' => __('tenant-blocks.common.button_styles.secondary'),
            ])
            ->default('primary'),
    ]);
```

### Data Structure

LinkInput stores this structure:

```json
{
  "type": "internal|external|email|phone|file|anchor",
  "page_id": 5,
  "url": "https://example.com",
  "email": "info@example.com",
  "phone": "+31201234567",
  "file_path": "/path/to/file.pdf",
  "anchor": "contact-section",
  "target": "_blank|_self"
}
```

### View Rendering

Always use the `<x-link>` component:

```blade
{{-- Basic --}}
<x-link :data="$button['link']" class="btn-primary">
    {{ $button['label'] }}
</x-link>

{{-- With conditional --}}
@php $linkData = $button['link'] ?? null; @endphp
@if ($linkData)
    <x-link :data="$linkData" class="btn">
        {{ $button['label'] ?? '' }}
    </x-link>
@endif

{{-- With inline styles --}}
<x-link
    :data="$linkData"
    class="inline-flex items-center px-6 py-3"
    style="background-color: var(--tenant-primary-500); color: white;"
>
    {{ $label }}
</x-link>
```

---

## ImagePicker

**Use for**: All images/media in block schemas. Never use FileUpload.

**Location**: `App\Forms\Components\ImagePicker`

### Schema Usage

```php
use App\Forms\Components\ImagePicker;

// Single image
ImagePicker::make('image')
    ->label(__('tenant-blocks.hero.fields.image'))
    ->conversion('large')
    ->helperText(__('tenant-blocks.hero.fields.image_helper'));

// Multiple images (gallery)
ImagePicker::make('gallery')
    ->label(__('tenant-blocks.gallery.fields.images'))
    ->multiple()
    ->maxFiles(10)
    ->reorderable();

// Video
ImagePicker::make('video')
    ->label(__('tenant-blocks.video.fields.video'))
    ->acceptsVideo();

// Background with mobile variant
ImagePicker::make('background_image')
    ->label(__('tenant-blocks.hero.fields.background_image'))
    ->acceptsVideo()
    ->conversion('large');
```

### Available Methods

| Method | Purpose |
|--------|---------|
| `->image()` | Accept only images |
| `->acceptsVideo()` | Accept images AND videos |
| `->video()` | Accept only videos |
| `->document()` | Accept only documents (PDF, DOC) |
| `->multiple()` | Allow selecting multiple files |
| `->maxFiles(n)` | Limit number of files |
| `->conversion('name')` | Set preview thumbnail (thumb, medium, large) |
| `->reorderable()` | Allow drag-to-reorder |

### View Rendering

Use the `media_url()` helper:

```blade
@php
$imageUrl = media_url($content['image']);
@endphp

@if ($imageUrl)
    <img
        src="{{ $imageUrl }}"
        alt="{{ $content['image_alt'] ?? '' }}"
        class="w-full h-full object-cover"
        loading="lazy"
    >
@endif
```

With conversions:

```blade
@php
$thumbUrl = media_url($content['image'], 'thumb');
$mediumUrl = media_url($content['image'], 'medium');
$largeUrl = media_url($content['image'], 'large');
@endphp
```

Responsive images:

```blade
<picture>
    <source media="(max-width: 767px)" srcset="{{ media_url($content['image'], 'medium') }}">
    <source media="(min-width: 768px)" srcset="{{ media_url($content['image'], 'large') }}">
    <img src="{{ media_url($content['image']) }}" alt="" class="w-full h-full object-cover">
</picture>
```

---

## RichTextEditorConfig

**Use for**: Consistent rich text editor configuration.

**Location**: `App\Forms\Components\RichTextEditorConfig`

### Schema Usage

```php
use App\Forms\Components\RichTextEditorConfig;

// Standard block description
RichTextEditorConfig::forBlock('description', __('tenant-blocks.hero.fields.description'));

// Custom toolbar
RichTextEditorConfig::forBlock('content', __('tenant-blocks.text.fields.content'))
    ->toolbarButtons(['bold', 'italic', 'link', 'bulletList', 'orderedList']);
```

### View Rendering

Use the `render_rich_text()` helper:

```blade
@php
$description = render_rich_text($content['description'] ?? '');
@endphp

@if ($description)
    <div class="prose prose-lg" style="color: var(--tenant-primary-800);">
        {!! $description !!}
    </div>
@endif
```

---

## ThemeConfigSection

**Use for**: Adding theme-specific text/color customization to blocks.

**Location**: `App\Forms\Components\ThemeConfigSection`

### Schema Usage

```php
use App\Forms\Components\ThemeConfigSection;

public static function getSchema(): array
{
    return [
        Section::make(__('tenant-blocks.hero.sections.content'))
            ->schema([
                // Regular fields...
            ]),

        // Add at the end of schema:
        ...ThemeConfigSection::make(self::class),
    ];
}
```

### Block Configuration

Define in your block class:

```php
use App\Blocks\Concerns\HasThemeConfiguration;

class YourBlock extends Block
{
    use HasThemeConfiguration;

    protected static function defineThemeConfig(string $layout): array
    {
        return match ($layout) {
            'smooth-commerce' => [
                'texts' => [
                    'cta_label' => [
                        'label' => __('tenant-blocks.your_block.fields.cta_label'),
                        'default' => 'Shop Now',
                    ],
                ],
                'colors' => [
                    'overlay' => [
                        'label' => __('tenant-blocks.your_block.colors.overlay'),
                        'default' => 'rgba(0,0,0,0.5)',
                    ],
                ],
            ],
            default => ['texts' => [], 'colors' => []],
        };
    }
}
```

### View Usage

```blade
@php
$theme = block_theme($content, $layout ?? 'elevate', \App\Blocks\YourBlock::class);
$ctaLabel = $theme->text('cta_label');
$overlayColor = $theme->color('overlay');
@endphp

<div style="background: {{ $overlayColor }};">
    <button>{{ $ctaLabel }}</button>
</div>
```

---

## HasLayoutFieldCapabilities Trait

**Use for**: Controlling which fields are visible for specific layouts.

### Block Configuration

```php
use App\Blocks\Concerns\HasLayoutFieldCapabilities;

class YourBlock extends Block
{
    use HasLayoutFieldCapabilities;

    protected static function defineFieldCapabilities(): array
    {
        return [
            // Only visible in elevate layout
            'eyebrow' => ['elevate'],

            // Visible in multiple layouts
            'stats' => ['elevate', 'momentum', 'bold-studio'],

            // Visible in all EXCEPT these (exclusion syntax)
            'show_badge' => ['!vitalis', '!pure-balance'],
        ];
    }
}
```

### Schema Usage

```php
public static function getSchema(): array
{
    return [
        TextInput::make('eyebrow')
            ->visible(static::visibleFor('eyebrow')),

        Section::make('Stats')
            ->schema([...])
            ->visible(static::visibleFor('stats')),
    ];
}
```

### Nested Field Visibility

For fields inside repeaters, the path is handled automatically:

```php
Repeater::make('items')
    ->schema([
        TextInput::make('eyebrow')
            // visibleFor() handles ../../layout path automatically
            ->visible(static::visibleFor('eyebrow')),
    ]),
```

---

---

## PaletteColorPicker

**Use for**: Color pickers that should show brand palette swatches.

**Location**: `App\Forms\Components\PaletteColorPicker`

### Schema Usage

```php
use App\Forms\Components\PaletteColorPicker;

// Shows brand palette swatches above color picker
PaletteColorPicker::make('background_color')
    ->label(__('tenant-blocks.your_block.fields.background_color'));

// Hide palette for fully custom colors
PaletteColorPicker::make('custom_color')
    ->hidePalette();
```

The palette shows all defined brand colors (primary, secondary, accent 1, accent 2) as clickable swatches.

---

## HasBackgroundOptions Trait

**Use for**: Blocks that need configurable backgrounds (color, image, overlay).

**Location**: `App\Blocks\Concerns\HasBackgroundOptions`

### Block Configuration

```php
use App\Blocks\Concerns\HasBackgroundOptions;

class YourBlock extends Block
{
    use HasBackgroundOptions;

    public static function getSchema(): array
    {
        return [
            // Your content sections...

            static::getBackgroundSection(),  // Add background options
        ];
    }

    public static function getDefaultContent(): array
    {
        return array_merge([
            'heading' => '',
            // ... your defaults
        ], static::getBackgroundDefaults());  // Include background defaults
    }
}
```

### What It Provides

The trait adds these fields:
- **background_type**: none | color | image
- **background_color**: PaletteColorPicker
- **background_image**: ImagePicker (supports video)
- **background_image_mobile**: ImagePicker for mobile
- **overlay_style**: none | light | medium | dark | custom
- **overlay_color**: PaletteColorPicker (for custom overlay)
- **overlay_opacity**: 0-100%
- **background_sticky**: Toggle for sticky/parallax effect

### View Usage

Use the `x-block-section` component which automatically includes the background:

```blade
{{-- Simple usage (background handled automatically) --}}
<x-block-section :content="$content" default-bg="var(--tenant-primary-50)">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {{-- Your content here --}}
    </div>
</x-block-section>

{{-- With decorations slot (for blur orbs, SVG patterns, etc.) --}}
<x-block-section :content="$content" default-bg="var(--tenant-primary-50)">
    <x-slot:decorations>
        <div class="pointer-events-none absolute inset-0">
            <div class="absolute -left-40 top-0 h-96 w-96 rounded-full blur-3xl"
                 style="background-color: color-mix(in srgb, var(--tenant-primary-200) 50%, transparent);"></div>
        </div>
    </x-slot:decorations>

    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {{-- Your content here --}}
    </div>
</x-block-section>

{{-- With theme-based background --}}
<x-block-section :content="$content" :default-bg="$theme->color('background')" style="{{ $theme->cssVars() }}">
    {{-- Content --}}
</x-block-section>

{{-- With custom padding/classes --}}
<x-block-section :content="$content" default-bg="white" class="py-24 lg:py-32">
    {{-- Content --}}
</x-block-section>
```

**Component Props:**
- `:content` - Block content array (reads background_type, background_image, etc.)
- `default-bg` - Fallback background when background_type is 'none'
- `class` - Custom classes (default: 'py-20 lg:py-28')
- Any additional attributes passed to the section

**Sticky/Parallax Backgrounds:**
When `background_sticky` is true, the background image will have a subtle parallax effect:
- GPU-accelerated with transform-based animation
- Respects `prefers-reduced-motion`
- Desktop-only (768px+ breakpoint)
- 40px movement range with smooth lerp animation

---

## Common Patterns

### Buttons Repeater

```php
Section::make(__('tenant-blocks.common.sections.buttons'))
    ->schema([
        Repeater::make('buttons')
            ->schema([
                TextInput::make('label')
                    ->label(__('tenant-blocks.common.fields.button_label'))
                    ->required()
                    ->maxLength(50),

                LinkInput::make('link'),

                Select::make('style')
                    ->label(__('tenant-blocks.common.fields.button_style'))
                    ->options([
                        'primary' => __('tenant-blocks.common.button_styles.primary'),
                        'secondary' => __('tenant-blocks.common.button_styles.secondary'),
                    ])
                    ->default('primary'),
            ])
            ->itemLabel(fn (array $state): string => $state['label'] ?? 'New Button')
            ->collapsible()
            ->collapsed()
            ->reorderable()
            ->defaultItems(0)
            ->maxItems(4)
            ->addActionLabel(__('tenant-blocks.common.fields.add_button')),
    ])
    ->collapsible()
    ->collapsed(),
```

### Stats Repeater

```php
Section::make(__('tenant-blocks.common.sections.stats'))
    ->schema([
        Repeater::make('stats')
            ->schema([
                Grid::make(2)->schema([
                    TextInput::make('value')
                        ->required()
                        ->maxLength(20)
                        ->placeholder('15+'),

                    TextInput::make('label')
                        ->required()
                        ->maxLength(50),
                ]),
            ])
            ->itemLabel(fn (array $state): string => ($state['value'] ?? '').' '.($state['label'] ?? ''))
            ->collapsible()
            ->collapsed()
            ->reorderable()
            ->defaultItems(0)
            ->maxItems(4),
    ])
    ->visible(static::visibleFor('stats'))
    ->collapsible()
    ->collapsed(),
```
