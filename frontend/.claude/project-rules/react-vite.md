# React + Vite Development Rules

This file defines rules and preferences for React development using Vite that Claude Code should follow.

## Project Setup

### Initialize New Projects

Use Vite's official scaffold with TypeScript template:

```bash
npm create vite@latest my-react-app -- --template react-ts
cd my-react-app
npm install
```

### Core Dependencies

Essential packages for a complete setup:

```bash
# Install React Router
npm install react-router-dom

# Install Storybook
npx storybook@latest init

# Install testing utilities
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom

# Install CSS Modules type definitions
npm install -D typescript-plugin-css-modules

# Install classnames for class concatenation
npm install classnames

# Install bundle analyzer
npm install -D rollup-plugin-visualizer
```

## Project Structure

Follow this standardized directory structure:

```
src/
├── components/           # Reusable UI components
│   └── Button/
│       ├── index.tsx           # Component implementation
│       ├── styles.module.css    # Component-specific styles
│       └── index.stories.ts    # Storybook stories
├── pages/               # Page layouts (no component definitions)
│   └── HomePage/
│       ├── index.tsx           # Page layout (imports components)
│       └── styles.module.css    # Page-specific styles
├── hooks/               # Custom React hooks
│   ├── useAuth.ts
│   └── useFetch.ts
├── api/                 # Backend API requests (grouped by domain)
│   ├── auth.ts
│   ├── users.ts
│   └── products.ts
├── types/               # TypeScript type definitions (grouped by domain)
│   ├── auth.ts
│   ├── user.ts
│   ├── product.ts
│   └── index.ts              # Optional: re-export all types
├── utils/               # Helper functions and utilities
│   ├── formatters.ts
│   └── validators.ts
├── assets/              # Static assets (images, fonts, icons)
│   ├── images/
│   ├── fonts/
│   └── icons/
├── App.tsx              # Main application component
├── main.tsx             # Application entry point
└── vite-env.d.ts        # Vite type declarations
```

### Structure Rules

1. **Components** - Each component must have:
   - `index.tsx` - Component implementation (must use `export default`)
   - `styles.module.css` - Component-specific styles using CSS Modules
   - `index.stories.ts` - Storybook stories (when using Storybook)

2. **Pages** - Page components should:
   - **Never contain component definitions** - only import and compose components
   - Define page layouts and data fetching
   - Handle routing and navigation logic
   - Import all UI components from `components/`

3. **Hooks** - Custom React hooks for:
   - Reusable stateful logic
   - Data fetching patterns
   - Side effects management

4. **API** - Group related API requests:
   - One file per domain/resource (e.g., `auth.ts`, `users.ts`)
   - Export functions for each API endpoint
   - Centralize API configuration and error handling

5. **Types** - Group related TypeScript types:
   - One file per domain (e.g., `auth.ts`, `user.ts`)
   - Optional `index.ts` to re-export all types
   - Keep types close to their usage domain

6. **Assets** - Static files:
   - Images, fonts, icons that are imported in code
   - Use `/public` for files that need direct serving

## Vite Configuration

### vite.config.ts

Configure Vite with optimal settings:

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import { resolve } from 'path';
import { visualizer } from 'rollup-plugin-visualizer';

export default defineConfig({
  plugins: [
    react(), // Use SWC for faster compilation
    visualizer({ open: true }), // Bundle analysis
  ],

  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@components': resolve(__dirname, 'src/components'),
      '@pages': resolve(__dirname, 'src/pages'),
      '@hooks': resolve(__dirname, 'src/hooks'),
      '@api': resolve(__dirname, 'src/api'),
      '@types': resolve(__dirname, 'src/types'),
      '@utils': resolve(__dirname, 'src/utils'),
      '@assets': resolve(__dirname, 'src/assets'),
    },
  },

  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },

  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },

  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom'],
  },
});
```

### tsconfig.json

Update TypeScript config to support path aliases:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"],
      "@components/*": ["src/components/*"],
      "@pages/*": ["src/pages/*"],
      "@hooks/*": ["src/hooks/*"],
      "@api/*": ["src/api/*"],
      "@types/*": ["src/types/*"],
      "@utils/*": ["src/utils/*"],
      "@assets/*": ["src/assets/*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

## Component Development

### Component Template

**IMPORTANT**: All `index.tsx` and `index.jsx` files must use `export default` for the main component.

```typescript
// src/components/Button/index.tsx
import React from 'react';
import classNames from 'classnames';
import styles from './styles.module.css';

interface ButtonProps {
  label: string;
  variant?: 'primary' | 'secondary';
  onClick?: () => void;
  disabled?: boolean;
}

const Button: React.FC<ButtonProps> = ({
  label,
  variant = 'primary',
  onClick,
  disabled = false,
}) => {
  return (
    <button
      className={classNames(styles.button, styles[`button--${variant}`])}
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  );
};

export default Button;
```

### CSS Modules

Use **BEM (Block Element Modifier)** naming convention:
- **Block**: Component name (`.button`, `.card`, `.nav`)
- **Element**: Child part using `__` (`.button__icon`, `.card__title`)
- **Modifier**: Variant/state using `--` (`.button--primary`, `.card--highlighted`)

Examples:
- `.button--primary` not `.buttonPrimary` or `.button-primary`
- `.nav__item` not `.navItem`
- `.form__input--error` for error state on form input

Access in JS: `styles['button--primary']` or `styles.buttonPrimary` (CSS Modules auto-converts)

### Class Concatenation with classnames

**When `classnames` is installed in the project, always use it for combining CSS classes.** Never use template literals or string concatenation.

```typescript
import classNames from 'classnames';
import styles from './styles.module.css';

// ✅ Correct - use classNames for all class concatenation
className={classNames(styles.button, styles['button--primary'])}

// ✅ Correct - conditional classes
className={classNames(styles.button, {
  [styles['button--active']]: isActive,
  [styles['button--disabled']]: disabled,
})}

// ✅ Correct - multiple conditions
className={classNames(
  styles.card,
  styles[`card--${variant}`],
  { [styles['card--highlighted']]: isHighlighted }
)}

// ❌ Wrong - template literals
className={`${styles.button} ${styles['button--primary']}`}

// ❌ Wrong - string concatenation
className={styles.button + ' ' + styles['button--primary']}

// ❌ Wrong - conditional with ternary in template
className={`${styles.button} ${isActive ? styles['button--active'] : ''}`}
```

```css
/* src/components/Button/styles.module.css */
.button {
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.2s ease;
}

.button--primary {
  background-color: #007bff;
  color: white;
}

.button--primary:hover {
  background-color: #0056b3;
}

.button--secondary {
  background-color: #6c757d;
  color: white;
}

.button--secondary:hover {
  background-color: #545b62;
}

.button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
```

### Storybook Stories

```typescript
// src/components/Button/index.stories.ts
import type { Meta, StoryObj } from '@storybook/react';
import Button from './index';

const meta: Meta<typeof Button> = {
  title: 'Components/Button',
  component: Button,
  tags: ['autodocs'],
  argTypes: {
    variant: {
      control: 'select',
      options: ['primary', 'secondary'],
    },
  },
};

export default meta;
type Story = StoryObj<typeof Button>;

export const Primary: Story = {
  args: {
    label: 'Primary Button',
    variant: 'primary',
  },
};

export const Secondary: Story = {
  args: {
    label: 'Secondary Button',
    variant: 'secondary',
  },
};

export const Disabled: Story = {
  args: {
    label: 'Disabled Button',
    disabled: true,
  },
};
```

## Page Development

### Page Template (Correct)

Pages should **only import and compose components**, never define them.
**IMPORTANT**: Page `index.tsx` files must also use `export default`.

```typescript
// src/pages/HomePage/index.tsx
import React, { useEffect, useState } from 'react';
import Button from '@components/Button';
import Header from '@components/Header';
import ProductList from '@components/ProductList';
import { useFetch } from '@hooks/useFetch';
import { getProducts } from '@api/products';
import type { Product } from '@types';
import styles from './styles.module.css';

const HomePage: React.FC = () => {
  const { data: products, loading, error } = useFetch<Product[]>(getProducts);

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div className={styles.container}>
      <Header title="Welcome to Our Store" />
      <ProductList products={products || []} />
      <Button
        label="View More"
        onClick={() => console.log('View more clicked')}
      />
    </div>
  );
};

export default HomePage;
```

### Page Anti-Pattern (Incorrect)

**Never do this** - defining components inside page files:

```typescript
// ❌ WRONG - Do not define components in page files
export const HomePage: React.FC = () => {
  // ❌ Component definition inside page
  const ProductCard = ({ product }) => (
    <div>{product.name}</div>
  );

  return (
    <div>
      <ProductCard product={product} />
    </div>
  );
};
```

## API Layer

### API Template

```typescript
// src/api/products.ts
import type { Product } from '@types';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

export const getProducts = async (): Promise<Product[]> => {
  const response = await fetch(`${API_BASE_URL}/products`);
  if (!response.ok) {
    throw new Error('Failed to fetch products');
  }
  return response.json();
};

export const getProductById = async (id: string): Promise<Product> => {
  const response = await fetch(`${API_BASE_URL}/products/${id}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch product ${id}`);
  }
  return response.json();
};

export const createProduct = async (
  product: Omit<Product, 'id'>
): Promise<Product> => {
  const response = await fetch(`${API_BASE_URL}/products`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(product),
  });
  if (!response.ok) {
    throw new Error('Failed to create product');
  }
  return response.json();
};
```

## Custom Hooks

### Hook Template

```typescript
// src/hooks/useFetch.ts
import { useState, useEffect } from 'react';

interface UseFetchResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
}

export const useFetch = <T>(
  fetchFn: () => Promise<T>
): UseFetchResult<T> => {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let isMounted = true;

    const fetchData = async () => {
      try {
        setLoading(true);
        const result = await fetchFn();
        if (isMounted) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setError(err as Error);
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      isMounted = false;
    };
  }, [fetchFn]);

  return { data, loading, error };
};
```

## Type Definitions

### Type Organization

Group related types in separate files:

```typescript
// src/types/product.ts
export interface Product {
  id: string;
  name: string;
  description: string;
  price: number;
  imageUrl: string;
  category: string;
  inStock: boolean;
}

export interface ProductFilters {
  category?: string;
  minPrice?: number;
  maxPrice?: number;
  inStock?: boolean;
}
```

```typescript
// src/types/user.ts
export interface User {
  id: string;
  email: string;
  name: string;
  role: 'admin' | 'user';
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  token: string | null;
}
```

```typescript
// src/types/index.ts
// Optional: Re-export all types for convenient importing
export * from './product';
export * from './user';
export * from './auth';
```

## Environment Variables

### .env Configuration

Create environment-specific files:

```bash
# .env.development
VITE_API_URL=http://localhost:5000
VITE_ENABLE_ANALYTICS=false

# .env.production
VITE_API_URL=https://api.example.com
VITE_ENABLE_ANALYTICS=true
```

### Usage

```typescript
// Access environment variables
const apiUrl = import.meta.env.VITE_API_URL;
const isDev = import.meta.env.DEV;
const isProd = import.meta.env.PROD;
```

### Type Declarations

```typescript
// src/vite-env.d.ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_ENABLE_ANALYTICS: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

## Performance Optimization

### Code Splitting

Use React lazy loading for route-based code splitting:

```typescript
// src/App.tsx
import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';

const HomePage = lazy(() => import('@pages/HomePage'));
const ProductPage = lazy(() => import('@pages/ProductPage'));
const AdminDashboard = lazy(() => import('@pages/AdminDashboard'));

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Suspense fallback={<div>Loading...</div>}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/products/:id" element={<ProductPage />} />
          <Route path="/admin" element={<AdminDashboard />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
};
```

### Dependency Optimization

Prefer ES module versions of libraries:
- ✅ `lodash-es` over `lodash`
- ✅ `date-fns` over `moment` (smaller, tree-shakeable)

Explicitly include/exclude dependencies:

```typescript
// vite.config.ts
export default defineConfig({
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom'],
    exclude: ['some-large-unneeded-lib'],
  },
});
```

## Testing

### Vitest Configuration

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react-swc';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@components': resolve(__dirname, 'src/components'),
      '@hooks': resolve(__dirname, 'src/hooks'),
    },
  },
});
```

### Test Setup

```typescript
// src/test/setup.ts
import { expect, afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom';

afterEach(() => {
  cleanup();
});
```

### Component Test Template

```typescript
// src/components/Button/__tests__/Button.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Button from '../index';

describe('Button', () => {
  it('renders with label', () => {
    render(<Button label="Click me" />);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const handleClick = vi.fn();
    render(<Button label="Click me" onClick={handleClick} />);

    await userEvent.click(screen.getByText('Click me'));
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it('is disabled when disabled prop is true', () => {
    render(<Button label="Click me" disabled />);
    expect(screen.getByText('Click me')).toBeDisabled();
  });
});
```

### Run Tests

```bash
# Run tests
npm run test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:coverage
```

## Code Quality

### ESLint Configuration

```javascript
// .eslintrc.cjs
module.exports = {
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
    'plugin:react/recommended',
  ],
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['react-refresh', '@typescript-eslint'],
  rules: {
    'react-refresh/only-export-components': 'warn',
    'react/react-in-jsx-scope': 'off',
  },
};
```

### Package Scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:watch": "vitest --watch",
    "test:coverage": "vitest --coverage",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "storybook": "storybook dev -p 6006",
    "build-storybook": "storybook build"
  }
}
```

## Best Practices

### General Rules

1. **Use TypeScript** - Strict mode enabled, no `any` types
2. **CSS Modules** - Always use CSS Modules for component styling
3. **classnames for classes** - When `classnames` is installed, always use it for class concatenation (never template literals)
4. **Path Aliases** - Use `@` prefixed aliases instead of relative imports
5. **Component Composition** - Pages should never define components
6. **Single Responsibility** - Each component should have one clear purpose
7. **Immutable State** - Never mutate state directly
8. **Default Exports** - All `index.tsx`/`index.jsx` must use `export default` for the main component

### Import Order

```typescript
// 1. React and third-party libraries
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import classNames from 'classnames';

// 2. Path-aliased imports (components use default imports, hooks/api use named)
import Button from '@components/Button';
import { useFetch } from '@hooks/useFetch';
import { getProducts } from '@api/products';

// 3. Types
import type { Product } from '@types';

// 4. Styles (always last)
import styles from './styles.module.css';
```

### Naming Conventions

- **Components**: PascalCase (`Button`, `ProductList`)
- **Hooks**: camelCase with `use` prefix (`useFetch`, `useAuth`)
- **API functions**: camelCase (`getProducts`, `createUser`)
- **Types/Interfaces**: PascalCase (`Product`, `User`)
- **CSS classes**: BEM convention (`.block__element--modifier`, e.g., `.card__title--highlighted`)
- **Files**: Match component name (`Button/index.tsx`)

### Performance Tips

1. **Lazy load routes** - Use `React.lazy()` for code splitting
2. **Memoize expensive calculations** - Use `useMemo` and `useCallback`
3. **Optimize re-renders** - Use `React.memo` for pure components
4. **Avoid inline object/array creation** - In props and dependencies
5. **Use SWC plugin** - Faster than Babel for compilation
6. **Analyze bundles** - Run visualizer to identify large dependencies

### Common Pitfalls to Avoid

1. ❌ Defining components inside page files
2. ❌ Using relative imports when path aliases are configured
3. ❌ Not using CSS Modules (using global styles instead)
4. ❌ Using template literals for class concatenation when `classnames` is available
5. ❌ Skipping Storybook stories for reusable components
6. ❌ Mixing API logic with component logic
7. ❌ Not grouping related types and API functions
8. ❌ Using `lodash` instead of `lodash-es`
9. ❌ Excessive plugins in Vite config
10. ❌ Not utilizing environment variables for config
11. ❌ Ignoring bundle size and not using code splitting

## Summary Checklist

When developing React + Vite projects, ensure:

- [ ] Project initialized with `npm create vite@latest -- --template react-ts`
- [ ] Path aliases configured in both `vite.config.ts` and `tsconfig.json`
- [ ] Components follow structure: `index.tsx`, `styles.module.css`, `index.stories.ts`
- [ ] Use `classnames` for all class concatenation (when installed)
- [ ] Pages only import components, never define them
- [ ] API functions grouped by domain in separate files
- [ ] Types grouped by domain with optional `index.ts`
- [ ] Custom hooks in dedicated `hooks/` directory
- [ ] CSS Modules used for all component styling
- [ ] Environment variables prefixed with `VITE_`
- [ ] Vitest configured for testing
- [ ] Code splitting implemented for routes
- [ ] SWC plugin enabled in Vite config
- [ ] ESLint and Prettier configured
- [ ] Storybook configured for component development
- [ ] Bundle analyzer available for optimization
