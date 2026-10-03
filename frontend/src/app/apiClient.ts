import { Api } from '../lib/api';
import { db } from '../lib/db';

/** The single API client for the app. Base URL is fixed at build time (VITE_API_URL). */
export const api = new Api({ baseUrl: __API_URL__, db });
