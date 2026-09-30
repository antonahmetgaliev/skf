/** Base path of the backend REST API. */
export const API = '/api/v1';

import type { components } from './api-schema';

/**
 * Request and response shapes, generated from the backend's OpenAPI spec
 * (`npm run api:types`). Never hand-write an API type; alias one of these.
 */
export type Schemas = components['schemas'];
