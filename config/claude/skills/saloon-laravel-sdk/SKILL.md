---
name: saloon-laravel-sdk
description: >
  Build PHP/Laravel API SDKs using Saloon v3, following the OhDear SDK structure as a reference.
  Use this skill whenever the user wants to build a Saloon-based SDK, API integration, or service
  layer in Laravel. Triggers include: "build an SDK with Saloon", "create a Saloon connector",
  "add a Saloon request", "Saloon DTO", "Saloon API integration", "build an API SDK in Laravel",
  or anytime the user wants to structure API calls with Request classes, Response DTOs, and a
  Connector following the OhDear / Saloon v3 conventions. Always use this skill — do not free-style
  Saloon code without reading it.
---

# Saloon Laravel SDK Skill

Build well-structured, type-safe PHP API SDKs using Saloon v3, following the conventions established by the [OhDear PHP SDK](https://github.com/ohdearapp/ohdear-php-sdk).

## Core Philosophy

- **One class per concern**: each API endpoint = one Request class
- **Namespaced by resource**: `Requests\Users\GetUserRequest`, `Requests\Orders\CreateOrderRequest`
- **Typed DTOs**: every response maps to a PHP data object via `createDtoFromResponse()`
- **Connector = entry point**: thin wrapper methods on the Connector call request classes
- **Data objects for request bodies**: use dedicated Data/DTO classes for POST/PUT bodies, not raw arrays

Read [`references/structure.md`](references/structure.md) for the full file layout.
Read [`references/patterns.md`](references/patterns.md) for code patterns with examples.

---

## Quick Decision Guide

| Task | What to build |
|---|---|
| New API integration | Connector + Request classes + DTOs |
| New endpoint | 1 Request class + 1 DTO (if response has structure) |
| POST/PUT body | Data object passed to Request constructor |
| Paginated list | Request + `HasPagination` on Connector |
| Laravel service | Connector bound via ServiceProvider + Facade |

---

## Step-by-Step Workflow

### 1. Install Saloon

```bash
composer require saloonphp/saloon
# For Laravel integration:
composer require saloonphp/laravel-plugin
php artisan saloon:install
```

### 2. Create the Connector

The Connector is the main entry point. Named after the service (e.g. `MyApiConnector`, `StripeConnector`).

```php
namespace App\Http\Integrations\MyApi;

use Saloon\Http\Connector;
use Saloon\Traits\Plugins\AcceptsJson;
use Saloon\Traits\Plugins\AlwaysThrowOnErrors;
use Saloon\Http\Auth\TokenAuthenticator;

class MyApiConnector extends Connector
{
    use AcceptsJson;
    use AlwaysThrowOnErrors;

    public function __construct(
        protected string $apiToken,
        protected string $baseUrl = 'https://api.example.com/v1',
        protected int $timeoutInSeconds = 10,
    ) {}

    public function resolveBaseUrl(): string
    {
        return $this->baseUrl;
    }

    protected function defaultAuth(): TokenAuthenticator
    {
        return new TokenAuthenticator($this->apiToken);
    }

    protected function defaultHeaders(): array
    {
        return [
            'Accept' => 'application/json',
            'Content-Type' => 'application/json',
        ];
    }

    protected function defaultConfig(): array
    {
        return ['timeout' => $this->timeoutInSeconds];
    }

    // Convenience methods — one per resource group
    public function users(): UserResource
    {
        return new UserResource($this);
    }
}
```

> **OhDear pattern**: convenience methods are either direct (return DTO) or delegate to a Resource class. For large SDKs, use Resource classes. For smaller SDKs, methods on the connector are fine.

### 3. Create Request Classes

One class per API endpoint. Grouped by resource in sub-namespaces.

**GET request:**
```php
namespace App\Http\Integrations\MyApi\Requests\Users;

use App\Http\Integrations\MyApi\DataObjects\User;
use Saloon\Enums\Method;
use Saloon\Http\Request;
use Saloon\Http\Response;

class GetUserRequest extends Request
{
    protected Method $method = Method::GET;

    public function __construct(
        protected int $userId
    ) {}

    public function resolveEndpoint(): string
    {
        return "/users/{$this->userId}";
    }

    public function createDtoFromResponse(Response $response): User
    {
        return User::fromArray($response->json());
    }
}
```

**POST request with body (using Data object):**
```php
namespace App\Http\Integrations\MyApi\Requests\Users;

use App\Http\Integrations\MyApi\DataObjects\User;
use App\Http\Integrations\MyApi\Data\CreateUserData;
use Saloon\Contracts\Body\HasBody;
use Saloon\Enums\Method;
use Saloon\Http\Request;
use Saloon\Http\Response;
use Saloon\Traits\Body\HasJsonBody;

class CreateUserRequest extends Request implements HasBody
{
    use HasJsonBody;

    protected Method $method = Method::POST;

    public function __construct(
        protected CreateUserData $data
    ) {}

    public function resolveEndpoint(): string
    {
        return '/users';
    }

    protected function defaultBody(): array
    {
        return $this->data->toArray();
    }

    public function createDtoFromResponse(Response $response): User
    {
        return User::fromArray($response->json());
    }
}
```

### 4. Create Data Objects (request bodies)

Used for POST/PUT/PATCH payloads. Clean, typed, serializable to array.

```php
namespace App\Http\Integrations\MyApi\Data;

class CreateUserData
{
    public function __construct(
        public readonly string $name,
        public readonly string $email,
        public readonly ?string $role = null,
    ) {}

    public function toArray(): array
    {
        return array_filter([
            'name' => $this->name,
            'email' => $this->email,
            'role' => $this->role,
        ], fn ($value) => $value !== null);
    }
}
```

### 5. Create Response DTOs

Map raw API response arrays to typed PHP objects.

```php
namespace App\Http\Integrations\MyApi\DataObjects;

class User
{
    public function __construct(
        public readonly int $id,
        public readonly string $name,
        public readonly string $email,
        public readonly ?string $role,
        public readonly string $createdAt,
    ) {}

    public static function fromArray(array $data): self
    {
        return new self(
            id: $data['id'],
            name: $data['name'],
            email: $data['email'],
            role: $data['role'] ?? null,
            createdAt: $data['created_at'],
        );
    }
}
```

### 6. Connector convenience methods

Add typed methods on the Connector (OhDear style) so callers don't need to construct requests:

```php
// On the Connector:
public function user(int $userId): User
{
    return $this->send(new GetUserRequest($userId))->dto();
}

public function createUser(CreateUserData $data): User
{
    return $this->send(new CreateUserRequest($data))->dto();
}

public function deleteUser(int $userId): void
{
    $this->send(new DeleteUserRequest($userId));
}
```

### 7. Laravel Service Provider binding (optional)

```php
// AppServiceProvider or dedicated IntegrationServiceProvider
$this->app->singleton(MyApiConnector::class, function () {
    return new MyApiConnector(
        apiToken: config('services.myapi.token'),
        baseUrl: config('services.myapi.base_url', 'https://api.example.com/v1'),
    );
});
```

---

## Namespace & Directory Structure

See [`references/structure.md`](references/structure.md) for the full layout. Summary:

```
app/Http/Integrations/{ServiceName}/
├── {ServiceName}Connector.php       # Connector (entry point)
├── Data/                            # Request body data objects
│   ├── CreateUserData.php
│   └── UpdateUserData.php
├── DataObjects/                     # Response DTOs
│   ├── User.php
│   └── Order.php
├── Requests/                        # One sub-namespace per resource
│   ├── Users/
│   │   ├── GetUserRequest.php
│   │   ├── GetUsersRequest.php
│   │   ├── CreateUserRequest.php
│   │   ├── UpdateUserRequest.php
│   │   └── DeleteUserRequest.php
│   └── Orders/
│       ├── GetOrderRequest.php
│       └── CreateOrderRequest.php
├── Resources/                       # (optional, for large SDKs)
│   └── UserResource.php
└── Exceptions/
    └── MyApiException.php
```

---

## Key Rules

1. **Request body = Data object**, not a raw array passed from caller
2. **Response = DTO**, always use `createDtoFromResponse()`, never return raw arrays
3. **Sub-namespace per resource**: `Requests\Users\`, `Requests\Orders\`, never `Requests\GetUser`
4. **Constructor injection in requests**: accept only what's needed for the endpoint
5. **`AlwaysThrowOnErrors`** on the Connector — let exceptions bubble, catch at call site
6. **`AcceptsJson`** on the Connector — sets `Accept: application/json` globally
7. **Readonly properties** on DTOs and Data objects — they're value objects, not mutable entities

For advanced patterns (pagination, error handling, testing, Resource classes), see [`references/patterns.md`](references/patterns.md).
