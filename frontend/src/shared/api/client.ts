import axios, { AxiosError } from 'axios';

import { errorDeLaApi } from './errorDeLaApi';
import { avisaDeSesionCaducada } from '@/shared/auth/sesionCaducada';

/**
 * Base de la API. Único sitio del frontend donde vive el host del servidor: el
 * resto del código construye rutas relativas y deja que este cliente las resuelva.
 * Sólo la hace falta explícita quien no pasa por axios — la redirección del SSO,
 * que es una navegación del navegador, no una petición.
 */
export const apiBaseUrl: string = import.meta.env.VITE_API_URL ?? '';

/**
 * El cliente con el token puesto. Se exporta porque hay una petición que no encaja en el
 * `customInstance` de Orval y no puede salirse del cliente: la **descarga de un fichero**, que
 * necesita `responseType: 'blob'` y la respuesta entera para leer el nombre del servidor. Ver
 * `download.ts`.
 */
export const apiClient = axios.create({ baseURL: apiBaseUrl });

const axiosInstance = apiClient;

axiosInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * El servidor devuelve el motivo del fallo en `detail.message` (#276: un formato único). Axios,
 * por su cuenta, deja un `message` genérico del tipo «Request failed with status code 409», y
 * las pantallas pintan `err.message`. Sin esta traducción, «Ya existe un chatbot por defecto» se
 * vería como un número de estado.
 */
axiosInstance.interceptors.response.use(undefined, (error: AxiosError<{ detail?: unknown }>) => {
  const detail = error.response?.data?.detail;
  // #278 — un 401 con token es que la sesión ya no vale: se cierra, en vez de dejar cada
  // pantalla fallando hasta que alguien recargue.
  if (error.response?.status === 401) {
    avisaDeSesionCaducada(error.config?.url, error.config?.headers?.Authorization);
  }
  const errorDelServidor = errorDeLaApi(error);
  if (errorDelServidor) {
    error.message = errorDelServidor.message;
  } else if (Array.isArray(detail)) {
    // Errores de validación de Pydantic: [{loc, msg, type}, …]
    const msgs = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : ''))
      .filter(Boolean);
    if (msgs.length) error.message = msgs.join('; ');
  }
  return Promise.reject(error);
});

export const customInstance = <T>(url: string, options?: RequestInit): Promise<T> => {
  return axiosInstance({
    url,
    method: options?.method ?? 'GET',
    data: options?.body,
    headers: options?.headers as Record<string, string> | undefined,
  }).then((r) => r.data);
};
