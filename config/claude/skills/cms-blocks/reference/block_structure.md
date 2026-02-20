# Block Class Structure

Complete template for creating new block classes.

## Full Block Template

```php
<?php

declare(strict_types=1);

namespace App\Blocks;

use App\Blocks\Concerns\HasLayoutFieldCapabilities;
use App\Blocks\Concerns\HasThemeConfiguration;
use App\Forms\Components\ImagePicker;
use App\Forms\Components\LinkInput;
use App\Forms\Components\RichTextEditorConfig;
use App\Forms\Components\ThemeConfigSection;
use Filament\Forms\Components\Repeater;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Components\Toggle;
use Filament\Schemas\Components\Grid;
use Filament\Schemas\Components\Section;

class YourNewBlock extends Block
{
    use HasLayoutFieldCapabilities;
    use HasThemeConfiguration;

    public static function getType(): string
    {
        return 'your-new-block';  // kebab-case, matches view folder
    }

    public static function getLabel(): string
    {
        return __('tenant-blocks.your_new_block.label');
    }

    public static function getIcon(): string
    {
        return 'heroicon-o-squares-2x2';
    }

    public static function getDescription(): string
    {
        return __('tenant-blocks.your_new_block.description');
    }

    public static function getCategory(): string
    {
        return __('tenant-blocks.categories.content');
    }

    public static function getLayouts(): array
    {
        return [
            'elevate' => __('tenant-blocks.your_new_block.layouts.elevate'),
            'vitalis' => __('tenant-blocks.your_new_block.layouts.vitalis'),
            // Add more themes as needed
        ];
    }

    public static function getDefaultLayout(): string
    {
        return 'elevate';
    }

    /**
     * Define which fields are restricted to specific layouts.
     * Fields not listed are visible in ALL layouts.
     *
     * @return array<string, array<string>>
     */
    protected static function defineFieldCapabilities(): array
    {
        return [
            'eyebrow' => ['elevate'],  // Only visible in elevate
            'stats' => ['elevate', 'momentum', 'bold-studio'],
            'show_badge' => ['!vitalis', '!pure-balance'],  // All except these
        ];
    }

    /**
     * Define theme-specific configuration for customizable text/colors.
     *
     * @return array{texts: array<string, array{label?: string, default?: string|array, help?: string}>, colors: array<string, array{label?: string, default?: string, help?: string}>}
     */
    protected static function defineThemeConfig(string $layout): array
    {
        return match ($layout) {
            'smooth-commerce' => [
                'texts' => [
                    'cta_label' => [
                        'label' => __('tenant-blocks.your_block.fields.cta_label'),
                        'default' => __('tenant-blocks.your_block.view_texts.cta_label'),
                    ],
                ],
                'colors' => [
                    'overlay_color' => [
                        'label' => __('tenant-blocks.your_block.colors.overlay'),
                        'default' => 'rgba(0,0,0,0.5)',
                    ],
                ],
            ],
            default => ['texts' => [], 'colors' => []],
        };
    }

    public static function getSchema(): array
    {
        return [
            Section::make(__('tenant-blocks.your_new_block.sections.content'))
                ->schema([
                    TextInput::make('heading')
                        ->label(__('tenant-blocks.your_new_block.fields.heading'))
                        ->required()
                        ->maxLength(200)
                        ->columnSpanFull(),

                    RichTextEditorConfig::forBlock('description', __('tenant-blocks.your_new_block.fields.description')),

                    ImagePicker::make('image')
                        ->label(__('tenant-blocks.your_new_block.fields.image'))
                        ->conversion('large')
                        ->helperText(__('tenant-blocks.your_new_block.fields.image_helper')),
                ])
                ->collapsible(),

            Section::make(__('tenant-blocks.your_new_block.sections.buttons'))
                ->schema([
                    Repeater::make('buttons')
                        ->label(__('tenant-blocks.your_new_block.fields.buttons'))
                        ->schema([
                            TextInput::make('label')
                                ->label(__('tenant-blocks.your_new_block.fields.button_label'))
                                ->required()
                                ->maxLength(50),

                            LinkInput::make('link'),  // ALWAYS use LinkInput for links

                            Select::make('style')
                                ->label(__('tenant-blocks.your_new_block.fields.button_style'))
                                ->options([
                                    'primary' => __('tenant-blocks.your_new_block.button_styles.primary'),
                                    'secondary' => __('tenant-blocks.your_new_block.button_styles.secondary'),
                                ])
                                ->default('primary'),
                        ])
                        ->itemLabel(fn (array $state): string => $state['label'] ?? __('tenant-blocks.your_new_block.fields.new_button'))
                        ->collapsible()
                        ->collapsed()
                        ->reorderable()
                        ->defaultItems(0)
                        ->maxItems(4)
                        ->addActionLabel(__('tenant-blocks.your_new_block.fields.add_button')),
                ])
                ->collapsible()
                ->collapsed(),

            Section::make(__('tenant-blocks.your_new_block.sections.layout_options'))
                ->schema([
                    TextInput::make('eyebrow')
                        ->label(__('tenant-blocks.your_new_block.fields.eyebrow'))
                        ->maxLength(60)
                        ->visible(static::visibleFor('eyebrow')),  // Layout-specific visibility
                ])
                ->visible(static::visibleFor('eyebrow'))
                ->collapsible()
                ->collapsed(),

            // Theme configuration section (colors, texts)
            ...ThemeConfigSection::make(self::class),
        ];
    }

    public static function getDefaultContent(): array
    {
        return [
            'heading' => '',
            'description' => '',
            'image' => null,
            'buttons' => [],
            'eyebrow' => '',
            'theme_config' => [
                'texts' => [],
                'colors' => [
                    'scheme' => 'brand',
                    'customize' => false,
                ],
            ],
        ];
    }

    /**
     * @param  array<string, mixed>  $content
     * @return array<string, string>
     */
    public static function validate(array $content): array
    {
        $errors = [];

        if (empty($content['heading'])) {
            $errors['heading'] = __('tenant-blocks.your_new_block.validation.heading_required');
        }

        return $errors;
    }

    public static function getPreviewView(): string
    {
        return 'blocks.your-new-block.elevate';
    }
}
```

## Required Methods

| Method | Purpose | Example Return |
|--------|---------|----------------|
| `getType()` | Unique identifier (kebab-case) | `'hero'` |
| `getLabel()` | Human-readable name | `__('tenant-blocks.hero.label')` |
| `getSchema()` | Filament form schema | `[Section::make(...)]` |
| `getPreviewView()` | Default Blade view | `'blocks.hero.elevate'` |

## Optional Methods

| Method | Purpose | Default |
|--------|---------|---------|
| `getIcon()` | Heroicon identifier | `'heroicon-o-cube'` |
| `getDescription()` | Block description | `''` |
| `getCategory()` | Grouping category | `'General'` |
| `getLayouts()` | Available themes | `['default' => 'Default']` |
| `getDefaultLayout()` | Default theme | First layout key |
| `getDefaultContent()` | Initial values | `[]` |
| `validate()` | Content validation | `[]` |

## Traits

### HasLayoutFieldCapabilities

Controls field visibility per layout:

```php
use HasLayoutFieldCapabilities;

protected static function defineFieldCapabilities(): array
{
    return [
        'eyebrow' => ['elevate'],           // Only in elevate
        'stats' => ['elevate', 'momentum'], // Only in these
        'show_badge' => ['!vitalis'],       // All except vitalis
    ];
}

// In schema:
TextInput::make('eyebrow')
    ->visible(static::visibleFor('eyebrow'));
```

### HasThemeConfiguration

Enables per-theme customizable text and colors:

```php
use HasThemeConfiguration;

protected static function defineThemeConfig(string $layout): array
{
    return match ($layout) {
        'smooth-commerce' => [
            'texts' => [
                'cta_label' => [
                    'label' => __('...'),
                    'default' => 'Shop Now',
                ],
            ],
            'colors' => [
                'overlay' => [
                    'label' => __('...'),
                    'default' => 'rgba(0,0,0,0.5)',
                ],
            ],
        ],
        default => ['texts' => [], 'colors' => []],
    };
}
```

Usage in view with `block_theme()` helper:

```blade
@php
$theme = block_theme($content, $layout, \App\Blocks\YourBlock::class);
$ctaLabel = $theme->text('cta_label');
$overlayColor = $theme->color('overlay');
@endphp
```
