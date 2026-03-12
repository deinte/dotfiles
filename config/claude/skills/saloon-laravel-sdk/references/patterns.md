# Saloon Laravel SDK — Code Patterns Reference

## 1. Connector Patterns

### Basic Connector with Token Auth

```php
<?php

namespace App\Http\Integrations\MyApi;

use Saloon\Http\Connector;
use Saloon\Http\Auth\TokenAuthenticator;
use Saloon\Traits\Plugins\AcceptsJson;
use Saloon\Traits\Plugins\AlwaysThrowOnErrors;

class MyApiConnector extends Connector
{
    use AcceptsJson;
    use AlwaysThrowOnErrors;

    public function __construct(
        protected readonly string $apiToken,
        protected readonly string $baseUrl = 'https://api.example.com/v1',
        protected readonly int $timeoutInSeconds = 10,
    ) {}

    public function resolveBaseUrl(): string
    {
        return $this->baseUrl;
    }

    protected function defaultAuth(): TokenAuthenticator
    {
        return new TokenAuthenticator($this->apiToken);
    }

    protected function defaultConfig(): array
    {
        return ['timeout' => $this->timeoutInSeconds];
    }

    // Convenience methods
    public function user(int $id): DataObjects\User
    {
        return $this->send(new Requests\Users\GetUserRequest($id))->dto();
    }

    public function users(): array
    {
        return $this->send(new Requests\Users\GetUsersRequest())->dto();
    }

    public function createUser(Data\CreateUserData $data): DataObjects\User
    {
        return $this->send(new Requests\Users\CreateUserRequest($data))->dto();
    }

    public function deleteUser(int $id): void
    {
        $this->send(new Requests\Users\DeleteUserRequest($id));
    }
}
```

### Connector with Basic Auth

```php
use Saloon\Http\Auth\BasicAuthenticator;

protected function defaultAuth(): BasicAuthenticator
{
    return new BasicAuthenticator($this->username, $this->password);
}
```

### Connector with OAuth2 / Bearer token header

```php
protected function defaultHeaders(): array
{
    return [
        'Authorization' => "Bearer {$this->apiToken}",
        'Accept' => 'application/json',
    ];
}
```

---

## 2. Request Patterns

### GET single resource

```php
<?php

namespace App\Http\Integrations\MyApi\Requests\Users;

use App\Http\Integrations\MyApi\DataObjects\User;
use Saloon\Enums\Method;
use Saloon\Http\Request;
use Saloon\Http\Response;

class GetUserRequest extends Request
{
    protected Method $method = Method::GET;

    public function __construct(
        protected readonly int $userId
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

### GET list of resources

```php
<?php

namespace App\Http\Integrations\MyApi\Requests\Users;

use App\Http\Integrations\MyApi\DataObjects\User;
use Saloon\Enums\Method;
use Saloon\Http\Request;
use Saloon\Http\Response;

class GetUsersRequest extends Request
{
    protected Method $method = Method::GET;

    public function __construct(
        protected readonly ?int $perPage = null,
        protected readonly ?int $page = null,
    ) {}

    public function resolveEndpoint(): string
    {
        return '/users';
    }

    protected function defaultQuery(): array
    {
        return array_filter([
            'per_page' => $this->perPage,
            'page' => $this->page,
        ], fn ($v) => $v !== null);
    }

    public function createDtoFromResponse(Response $response): array
    {
        return array_map(
            fn (array $user) => User::fromArray($user),
            $response->json('data') ?? $response->json()
        );
    }
}
```

### POST request with Data object body

```php
<?php

namespace App\Http\Integrations\MyApi\Requests\Users;

use App\Http\Integrations\MyApi\Data\CreateUserData;
use App\Http\Integrations\MyApi\DataObjects\User;
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
        protected readonly CreateUserData $data
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

### PUT/PATCH request

```php
<?php

namespace App\Http\Integrations\MyApi\Requests\Users;

use App\Http\Integrations\MyApi\Data\UpdateUserData;
use App\Http\Integrations\MyApi\DataObjects\User;
use Saloon\Contracts\Body\HasBody;
use Saloon\Enums\Method;
use Saloon\Http\Request;
use Saloon\Http\Response;
use Saloon\Traits\Body\HasJsonBody;

class UpdateUserRequest extends Request implements HasBody
{
    use HasJsonBody;

    protected Method $method = Method::PUT;

    public function __construct(
        protected readonly int $userId,
        protected readonly UpdateUserData $data
    ) {}

    public function resolveEndpoint(): string
    {
        return "/users/{$this->userId}";
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

### DELETE request (no response body)

```php
<?php

namespace App\Http\Integrations\MyApi\Requests\Users;

use Saloon\Enums\Method;
use Saloon\Http\Request;

class DeleteUserRequest extends Request
{
    protected Method $method = Method::DELETE;

    public function __construct(
        protected readonly int $userId
    ) {}

    public function resolveEndpoint(): string
    {
        return "/users/{$this->userId}";
    }
}
```

---

## 3. Data Object Patterns (request bodies)

### Create data object

```php
<?php

namespace App\Http\Integrations\MyApi\Data;

class CreateUserData
{
    public function __construct(
        public readonly string $name,
        public readonly string $email,
        public readonly string $role,
        public readonly ?string $phone = null,
        public readonly ?int $teamId = null,
    ) {}

    public function toArray(): array
    {
        return array_filter([
            'name' => $this->name,
            'email' => $this->email,
            'role' => $this->role,
            'phone' => $this->phone,
            'team_id' => $this->teamId,
        ], fn ($value) => $value !== null);
    }
}
```

### Update data object (all fields optional)

```php
<?php

namespace App\Http\Integrations\MyApi\Data;

class UpdateUserData
{
    public function __construct(
        public readonly ?string $name = null,
        public readonly ?string $email = null,
        public readonly ?string $role = null,
    ) {}

    public function toArray(): array
    {
        // Only send fields that were explicitly set
        return array_filter([
            'name' => $this->name,
            'email' => $this->email,
            'role' => $this->role,
        ], fn ($value) => $value !== null);
    }
}
```

---

## 4. Response DTO Patterns

### Simple DTO

```php
<?php

namespace App\Http\Integrations\MyApi\DataObjects;

class User
{
    public function __construct(
        public readonly int $id,
        public readonly string $name,
        public readonly string $email,
        public readonly string $role,
        public readonly ?string $phone,
        public readonly ?int $teamId,
        public readonly string $createdAt,
        public readonly ?string $updatedAt,
    ) {}

    public static function fromArray(array $data): self
    {
        return new self(
            id: $data['id'],
            name: $data['name'],
            email: $data['email'],
            role: $data['role'],
            phone: $data['phone'] ?? null,
            teamId: $data['team_id'] ?? null,
            createdAt: $data['created_at'],
            updatedAt: $data['updated_at'] ?? null,
        );
    }
}
```

### DTO with nested objects

```php
<?php

namespace App\Http\Integrations\MyApi\DataObjects;

class Order
{
    public function __construct(
        public readonly int $id,
        public readonly string $status,
        public readonly User $user,           // nested DTO
        public readonly array $items,          // array of OrderItem DTOs
        public readonly float $total,
        public readonly string $createdAt,
    ) {}

    public static function fromArray(array $data): self
    {
        return new self(
            id: $data['id'],
            status: $data['status'],
            user: User::fromArray($data['user']),
            items: array_map(
                fn (array $item) => OrderItem::fromArray($item),
                $data['items'] ?? []
            ),
            total: (float) $data['total'],
            createdAt: $data['created_at'],
        );
    }
}
```

---

## 5. Resource Class Pattern (for large SDKs)

When the Connector gets too large, delegate to Resource classes:

```php
<?php

namespace App\Http\Integrations\MyApi\Resources;

use App\Http\Integrations\MyApi\Data\CreateUserData;
use App\Http\Integrations\MyApi\Data\UpdateUserData;
use App\Http\Integrations\MyApi\DataObjects\User;
use App\Http\Integrations\MyApi\Requests\Users\CreateUserRequest;
use App\Http\Integrations\MyApi\Requests\Users\DeleteUserRequest;
use App\Http\Integrations\MyApi\Requests\Users\GetUserRequest;
use App\Http\Integrations\MyApi\Requests\Users\GetUsersRequest;
use App\Http\Integrations\MyApi\Requests\Users\UpdateUserRequest;
use Saloon\Http\Connector;

class UserResource
{
    public function __construct(
        protected readonly Connector $connector
    ) {}

    public function all(): array
    {
        return $this->connector->send(new GetUsersRequest())->dto();
    }

    public function find(int $id): User
    {
        return $this->connector->send(new GetUserRequest($id))->dto();
    }

    public function create(CreateUserData $data): User
    {
        return $this->connector->send(new CreateUserRequest($data))->dto();
    }

    public function update(int $id, UpdateUserData $data): User
    {
        return $this->connector->send(new UpdateUserRequest($id, $data))->dto();
    }

    public function delete(int $id): void
    {
        $this->connector->send(new DeleteUserRequest($id));
    }
}
```

On the Connector:

```php
public function users(): UserResource
{
    return new UserResource($this);
}
```

Usage:
```php
$connector->users()->find(1);
$connector->users()->create(new CreateUserData(...));
```

---

## 6. Exception Handling

```php
<?php

namespace App\Http\Integrations\MyApi\Exceptions;

use Saloon\Exceptions\Request\RequestException;

class MyApiException extends RequestException
{
    //
}
```

```php
// ValidationException for 422 responses
class ValidationException extends MyApiException
{
    public function errors(): array
    {
        return $this->response->json('errors') ?? [];
    }
}
```

Custom error handling on the Connector:

```php
use Saloon\Http\Response;
use Saloon\Exceptions\Request\RequestException;

public function handleResponse(Response $response): void
{
    if ($response->status() === 422) {
        throw new ValidationException($response->getPendingRequest(), $response);
    }

    parent::handleResponse($response);
}
```

---

## 7. Pagination Pattern

```php
use Saloon\Http\Connector;
use Saloon\Contracts\Paginator;
use Saloon\PaginationPlugin\PagedPaginator;
use Saloon\PaginationPlugin\Contracts\HasPagination;

class MyApiConnector extends Connector implements HasPagination
{
    public function paginate(Request $request): PagedPaginator
    {
        return new class(connector: $this, request: $request) extends PagedPaginator
        {
            protected function isLastPage(Response $response): bool
            {
                return is_null($response->json('next_page_url'));
            }

            protected function getPageItems(Response $response, Request $request): array
            {
                return $response->json('data') ?? [];
            }
        };
    }
}

// Usage with iterator (OhDear style):
public function users(): \Generator
{
    $paginator = $this->paginate(new GetUsersRequest());

    foreach ($paginator as $response) {
        foreach ($response->json('data') as $userData) {
            yield User::fromArray($userData);
        }
    }
}
```

---

## 8. Testing Pattern (Saloon MockClient)

```php
use Saloon\Http\Faking\MockClient;
use Saloon\Http\Faking\MockResponse;

it('can get a user', function () {
    MockClient::global([
        GetUserRequest::class => MockResponse::make([
            'id' => 1,
            'name' => 'Jane Doe',
            'email' => 'jane@example.com',
            'role' => 'admin',
            'created_at' => '2024-01-01T00:00:00Z',
        ], 200),
    ]);

    $connector = new MyApiConnector('fake-token');
    $user = $connector->user(1);

    expect($user)->toBeInstanceOf(User::class);
    expect($user->name)->toBe('Jane Doe');
    expect($user->email)->toBe('jane@example.com');
});

it('can create a user', function () {
    MockClient::global([
        CreateUserRequest::class => MockResponse::make([
            'id' => 42,
            'name' => 'John Doe',
            'email' => 'john@example.com',
            'role' => 'user',
            'created_at' => '2024-01-01T00:00:00Z',
        ], 201),
    ]);

    $connector = new MyApiConnector('fake-token');
    $user = $connector->createUser(new CreateUserData(
        name: 'John Doe',
        email: 'john@example.com',
        role: 'user',
    ));

    expect($user->id)->toBe(42);
});
```

### Fixture-based testing (snapshot style)

```php
// First run: hits real API and records response to tests/Fixtures/getUser.json
// Subsequent runs: uses fixture file (fast, offline)

MockClient::global([
    GetUserRequest::class => MockResponse::fixture('getUser'),
]);
```

---

## 9. Laravel Service Provider & Facade

```php
// app/Providers/AppServiceProvider.php or dedicated IntegrationServiceProvider

public function register(): void
{
    $this->app->singleton(MyApiConnector::class, function () {
        return new MyApiConnector(
            apiToken: config('services.myapi.token'),
        );
    });
}
```

```php
// Usage in controllers / services
class UserController extends Controller
{
    public function __construct(
        protected readonly MyApiConnector $myApi
    ) {}

    public function show(int $id): JsonResponse
    {
        $user = $this->myApi->user($id);
        return response()->json($user);
    }
}
```

---

## 10. Common Mistakes to Avoid

| ❌ Wrong | ✅ Correct |
|---|---|
| Raw `array` as POST body passed from caller | Create a `Data` object (`CreateUserData`) |
| Returning `$response->json()` from connector methods | Return typed DTOs |
| All requests in one `Requests/` folder | Sub-namespaces: `Requests/Users/`, `Requests/Orders/` |
| `GetUser` as request name | `GetUserRequest` (always suffix with `Request`) |
| Mutable DTO properties | `readonly` constructor properties |
| Giant connector with all logic inline | Delegate to Resource classes or Request classes |
| Catching exceptions in request classes | Let `AlwaysThrowOnErrors` bubble up; catch at call site |
