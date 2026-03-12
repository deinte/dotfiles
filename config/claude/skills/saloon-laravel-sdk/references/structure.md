# Saloon Laravel SDK — Directory Structure Reference

## Full Layout (OhDear-style)

```
app/Http/Integrations/{ServiceName}/
│
├── {ServiceName}Connector.php
│   └── The main Connector class. Holds baseUrl, auth, headers, config.
│       Exposes convenience methods or delegates to Resource classes.
│
├── Data/                              # Request body data objects (inputs)
│   ├── CreateUserData.php             # For POST /users
│   ├── UpdateUserData.php             # For PUT /users/{id}
│   └── CreateOrderData.php
│
├── DataObjects/                       # Response DTOs (outputs)
│   ├── User.php
│   ├── UserCollection.php             # (if needed for paginated list)
│   ├── Order.php
│   └── PaginatedResult.php            # (generic paginated wrapper if needed)
│
├── Requests/                          # One sub-namespace per API resource
│   ├── Users/
│   │   ├── GetUsersRequest.php        # GET /users
│   │   ├── GetUserRequest.php         # GET /users/{id}
│   │   ├── CreateUserRequest.php      # POST /users
│   │   ├── UpdateUserRequest.php      # PUT /users/{id}
│   │   └── DeleteUserRequest.php      # DELETE /users/{id}
│   │
│   ├── Orders/
│   │   ├── GetOrdersRequest.php
│   │   ├── GetOrderRequest.php
│   │   └── CreateOrderRequest.php
│   │
│   └── Account/
│       └── GetMeRequest.php           # GET /me (user info)
│
├── Resources/                         # Optional — for large SDKs only
│   ├── UserResource.php               # Groups User request methods
│   └── OrderResource.php
│
├── Exceptions/
│   ├── {ServiceName}Exception.php     # Base exception
│   └── ValidationException.php        # For 422 errors with field-level errors
│
└── Concerns/                          # Shared traits for the connector
    └── ManagesUsers.php               # (optional, to keep connector slim)
```

## Naming Conventions

| Class type | Name pattern | Example |
|---|---|---|
| Connector | `{Service}Connector` | `StripeConnector`, `MyApiConnector` |
| Request | `{Verb}{Resource}Request` | `GetUserRequest`, `CreateOrderRequest` |
| Response DTO | `{Resource}` (singular) | `User`, `Order`, `Invoice` |
| Request body Data | `{Verb}{Resource}Data` | `CreateUserData`, `UpdateOrderData` |
| Resource class | `{Resource}Resource` | `UserResource`, `OrderResource` |
| Exception | `{Service}Exception` | `StripeException` |

## Verb conventions for Request naming

| HTTP method | Verb prefix |
|---|---|
| GET (single) | `Get` |
| GET (list) | `Get` (plural resource) |
| POST | `Create` |
| PUT / PATCH | `Update` |
| DELETE | `Delete` |
| Custom actions | Descriptive verb: `Enable`, `Disable`, `Snooze`, `Resend` |

## Laravel config/env binding

```php
// config/services.php
'myapi' => [
    'token' => env('MYAPI_TOKEN'),
    'base_url' => env('MYAPI_BASE_URL', 'https://api.example.com/v1'),
],
```

```php
// .env
MYAPI_TOKEN=your-api-token-here
MYAPI_BASE_URL=https://api.example.com/v1
```

## Artisan generation commands (saloonphp/laravel-plugin)

```bash
# Generate a connector
php artisan saloon:connector MyApi/MyApiConnector

# Generate a request
php artisan saloon:request MyApi/Users/GetUserRequest

# Note: DTOs and Data objects are handwritten — Saloon doesn't generate them
```
