# Block View Patterns

Standard patterns for Blade views in content blocks.

## View Structure Template

```blade
{{-- Block Name - Theme Description --}}
@php
    // 1. Extract ALL content with fallbacks
    $heading = $content['heading'] ?? '';
    $subheading = $content['subheading'] ?? '';
    $description = render_rich_text($content['description'] ?? '');
    $buttons = $content['buttons'] ?? [];
    $items = $content['items'] ?? [];
    $image = $content['image'] ?? null;

    // 2. Optional: Theme configuration
    $theme = block_theme($content, $layout ?? 'elevate', \App\Blocks\YourBlock::class);
    $ctaLabel = $theme->text('cta_label');
@endphp

<x-block-section :content="$content" default-bg="var(--tenant-primary-50)">
    <x-slot:decorations>
        {{-- Background decorations, overlays --}}
    </x-slot:decorations>

    {{-- Main content --}}
    <div class="container mx-auto px-4 py-16">
        @if ($heading)
            <h2 style="color: var(--tenant-primary-900);">{{ $heading }}</h2>
        @endif

        {{-- More content... --}}
    </div>
</x-block-section>
```

## Content Extraction

Always extract content variables at the top of the view:

```blade
@php
    // Text content
    $heading = $content['heading'] ?? '';
    $subheading = $content['subheading'] ?? '';
    $eyebrow = $content['eyebrow'] ?? '';

    // Rich text (requires helper)
    $description = render_rich_text($content['description'] ?? '');

    // Media
    $image = $content['image'] ?? null;
    $backgroundImage = $content['background_image'] ?? null;

    // Arrays
    $buttons = $content['buttons'] ?? [];
    $items = $content['items'] ?? [];
    $stats = $content['stats'] ?? [];

    // Booleans
    $showOverlay = $content['show_overlay'] ?? true;
    $showBadge = $content['show_badge'] ?? false;

    // Options
    $textAlignment = $content['text_alignment'] ?? 'center';
    $height = $content['height'] ?? 'full';
@endphp
```

## Block Section Wrapper

Use `<x-block-section>` for consistent section handling:

```blade
<x-block-section
    :content="$content"
    default-bg="var(--tenant-primary-50)"
    class="py-16 lg:py-24"
>
    {{-- Content here --}}
</x-block-section>
```

With decorations slot for backgrounds:

```blade
<x-block-section :content="$content" default-bg="var(--tenant-primary-900)">
    <x-slot:decorations>
        {{-- Background image --}}
        @include('blocks.hero._background', [
            'background' => $backgroundImage,
            'conversion' => 'large',
        ])

        {{-- Overlay --}}
        @if ($showOverlay)
            <div class="absolute inset-0 z-[1]" style="background: linear-gradient(to bottom, color-mix(in srgb, var(--tenant-primary-900) 70%, transparent), color-mix(in srgb, var(--tenant-primary-900) 50%, transparent));"></div>
        @endif
    </x-slot:decorations>

    {{-- Content --}}
</x-block-section>
```

## Image Rendering

Use the `media_url()` helper:

```blade
@php
$imageUrl = media_url($content['image']);
$thumbUrl = media_url($content['image'], 'thumb');
$largeUrl = media_url($content['image'], 'large');
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

Responsive images with picture element:

```blade
<picture>
    <source media="(max-width: 767px)" srcset="{{ media_url($content['image'], 'medium') }}">
    <source media="(min-width: 768px)" srcset="{{ media_url($content['image'], 'large') }}">
    <img src="{{ media_url($content['image']) }}" alt="" class="w-full h-full object-cover">
</picture>
```

## Link Rendering

Always use the `<x-link>` component:

```blade
{{-- Basic link --}}
<x-link :data="$button['link']" class="btn-primary">
    {{ $button['label'] }}
</x-link>

{{-- With conditional rendering --}}
@if ($button['link'])
    <x-link
        :data="$button['link']"
        class="inline-flex items-center px-6 py-3 font-semibold"
        style="background-color: var(--tenant-primary-500); color: white;"
    >
        {{ $button['label'] }}
    </x-link>
@endif

{{-- Loop through buttons --}}
@foreach ($buttons as $button)
    @php $linkData = $button['link'] ?? null; @endphp
    @if ($linkData)
        <x-link :data="$linkData" class="btn">
            {{ $button['label'] ?? '' }}
        </x-link>
    @endif
@endforeach
```

## Theme Configuration Helper

For blocks using `HasThemeConfiguration`:

```blade
@php
$theme = block_theme($content, $layout ?? 'elevate', \App\Blocks\YourBlock::class);

// Get configurable text (with fallback to default)
$ctaLabel = $theme->text('cta_label');
$swipeHint = $theme->text('swipe_hint');

// Get configurable color
$overlayColor = $theme->color('overlay_gradient');
$buttonBg = $theme->color('button_primary_bg');
@endphp

<div style="background: {{ $overlayColor }};">
    <button style="background: {{ $buttonBg }};">{{ $ctaLabel }}</button>
</div>
```

## Umami Analytics

Add tracking to interactive elements:

```blade
{{-- On clickable elements --}}
<x-link
    :data="$linkData"
    {!! umami_track('hero_cta_click', ['label' => $button['label']]) !!}
>
    {{ $button['label'] }}
</x-link>

{{-- With Alpine.js --}}
<button
    @click="open = !open; {{ umami_event_code('faq_toggle', ['index' => $index]) }}"
    {!! umami_track('faq_toggle', ['index' => $index]) !!}
>
    {{ $question }}
</button>

{{-- Page-load events --}}
@if ($showSuccess)
    {!! umami_event('form_success', ['form_id' => $formId]) !!}
@endif
```

## Common Patterns

### Container with responsive padding

```blade
<div class="container mx-auto px-4 sm:px-6 lg:px-8">
```

### Responsive grids

```blade
{{-- 2 columns on large --}}
<div class="grid gap-8 lg:grid-cols-2">

{{-- 3 columns on medium, 2 on small --}}
<div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">

{{-- 4 columns with responsive fallback --}}
<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
```

### Conditional sections

```blade
@if ($heading || $subheading)
    <div class="text-center mb-12">
        @if ($heading)
            <h2 style="color: var(--tenant-primary-900);">{{ $heading }}</h2>
        @endif
        @if ($subheading)
            <p style="color: var(--tenant-primary-600);">{{ $subheading }}</p>
        @endif
    </div>
@endif
```

### Looping with index

```blade
@foreach ($items as $index => $item)
    <div class="{{ $loop->first ? 'border-t' : '' }} {{ $loop->last ? 'rounded-b' : '' }}">
        <span>{{ $index + 1 }}</span>
        <h3>{{ $item['title'] ?? '' }}</h3>
    </div>
@endforeach
```

## What NOT to Do

```blade
{{-- WRONG - Hardcoded text --}}
<h2>Welcome to Our Site</h2>

{{-- WRONG - Translation call --}}
<span>{{ __('tenant-blocks.hero.cta') }}</span>

{{-- WRONG - Hardcoded color --}}
<div style="background: #3b82f6;">

{{-- WRONG - Direct URL access --}}
<a href="{{ $button['url'] }}">

{{-- WRONG - Inline media queries --}}
<div style="@media (min-width: 768px) { width: 50%; }">
```

## What TO Do

```blade
{{-- RIGHT - From content field --}}
<h2>{{ $heading }}</h2>

{{-- RIGHT - Theme config text --}}
<span>{{ $theme->text('cta_label') }}</span>

{{-- RIGHT - Tenant CSS variable --}}
<div style="background: var(--tenant-primary-500);">

{{-- RIGHT - x-link component --}}
<x-link :data="$button['link']">{{ $button['label'] }}</x-link>

{{-- RIGHT - Style block for media queries --}}
<style>
    .responsive-element { width: 100%; }
    @media (min-width: 768px) { .responsive-element { width: 50%; } }
</style>
```
