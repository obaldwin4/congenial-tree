import { createApi, fetchBaseQuery, FetchBaseQueryError } from '@reduxjs/toolkit/query/react';

// Define a minimal interface for auth state to avoid circular dependencies
interface AuthState {
  token: string | null;
}

interface StoreState {
  auth: AuthState;
}

// Base API setup with authentication handling and error management
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/1/',
    prepareHeaders: (headers, { getState }) => {
      // Get the token from auth state
      const state = getState() as StoreState;
      const token = state.auth.token;
      
      // If we have a token, include it in all requests
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }
      
      headers.set('Content-Type', 'application/json');
      return headers;
    },
    // Handle response preprocessing for standardized API response format
    responseHandler: async (response) => {
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        return Promise.reject(error || { message: 'Server error' });
      }
      
      try {
        const data = await response.json();
        // Our backend wraps responses in a standard format { result, message }
        if (data.message && !data.result) {
          return Promise.reject({ message: data.message });
        }
        return data.result;
      } catch (error) {
        return Promise.reject({ message: 'Failed to parse server response' });
      }
    },
  }),
  endpoints: () => ({}),
  // Define tags for cache invalidation
  tagTypes: [
    'User',
    'Settings',
    'Exchange',
    'Balance',
    'Trade',
    'Transaction',
    'LedgerAction',
    'BlockchainAccount',
    'DeFiPosition',
    'Asset',
    'Price',
    'Statistics',
    'Wallet'
  ],
});

// Export the base API to be extended by feature-specific APIs
export default baseApi;

// The hooks are automatically generated by RTK Query when using the
// code-generation utilities of createApi - we don't need to manually export them
