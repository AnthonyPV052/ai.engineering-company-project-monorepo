/**
 * Módulo de integración con los endpoints /inventory de la API de Brasaland.
 *
 * Ningún componente debe llamar a fetch directamente. Todas las funciones
 * de este módulo gestionan automáticamente la cabecera Authorization y
 * propagan los errores de la API como excepciones ApiError.
 *
 * @module lib/inventory
 */

import { authenticatedApiFetch, API_BASE } from "@/lib/auth";

// ============================================================================
// Tipos compartidos (reflejan los schemas Pydantic del backend)
// ============================================================================

export interface IngredientCreatePayload {
  name: string;
  sku: string;
  unit: string;
  category: string;
  country: string;
}

export interface IngredientResponse {
  id: number;
  name: string;
  sku: string;
  unit: string;
  category: string;
  country: string;
  current_stock: number;
}

export interface IngredientEntryCreatePayload {
  ingredient_id: number;
  quantity: number;
  supplier_name: string;
  location_id: number;
}

export interface IngredientEntryResponse {
  id: number;
  ingredient_id: number;
  quantity: number;
  supplier_name: string;
  location_id: number;
  created_at: string;
  user_uuid: string;
}

export interface IngredientExitCreatePayload {
  ingredient_id: number;
  quantity: number;
  reason: "consumption" | "waste";
  location_id: number;
}

export interface IngredientExitResponse {
  id: number;
  ingredient_id: number;
  quantity: number;
  reason: string;
  location_id: number;
  created_at: string;
  user_uuid: string;
}

export interface IngredientOrderEntry {
  id: number;
  type: "entry" | "exit";
  ingredient_id: number;
  ingredient_name: string;
  ingredient_sku: string;
  quantity: number;
  supplier_name: string | null;
  reason: string | null;
  location_id: number;
  created_at: string;
  user_uuid: string;
}

// ============================================================================
// Productos (Ingredientes)
// ============================================================================

/**
 * GET /inventory/products
 * Lista todos los ingredientes con su stock actual.
 *
 * @param country  Código de país opcional para filtrar ("CO" | "US")
 */
export async function fetchProducts(country?: string): Promise<IngredientResponse[]> {
  const query = country ? `?country=${encodeURIComponent(country)}` : "";
  return authenticatedApiFetch<IngredientResponse[]>(`/inventory/products${query}`);
}

/**
 * POST /inventory/products
 * Crea un nuevo ingrediente en el inventario.
 */
export async function createProduct(payload: IngredientCreatePayload): Promise<IngredientResponse> {
  return authenticatedApiFetch<IngredientResponse>("/inventory/products", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * GET /inventory/products/{id}
 * Obtiene un ingrediente por ID con su stock actual.
 */
export async function fetchProductById(id: number): Promise<IngredientResponse> {
  return authenticatedApiFetch<IngredientResponse>(`/inventory/products/${id}`);
}

// ============================================================================
// Órdenes de entrada (inbound)
// ============================================================================

/**
 * POST /inventory/orders/inbound
 * Registra una entrega de ingrediente recibida de un proveedor.
 */
export async function createInboundOrder(
  payload: IngredientEntryCreatePayload,
): Promise<IngredientEntryResponse> {
  return authenticatedApiFetch<IngredientEntryResponse>("/inventory/orders/inbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ============================================================================
// Órdenes de salida (outbound)
// ============================================================================

/**
 * POST /inventory/orders/outbound
 * Registra un consumo o merma de ingrediente.
 *
 * Lanza ApiError si el stock es insuficiente o el motivo no es válido.
 */
export async function createOutboundOrder(
  payload: IngredientExitCreatePayload,
): Promise<IngredientExitResponse> {
  return authenticatedApiFetch<IngredientExitResponse>("/inventory/orders/outbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ============================================================================
// Listado completo de órdenes
// ============================================================================

/**
 * GET /inventory/orders
 * Lista todas las entradas y salidas con datos del ingrediente asociado,
 * ordenadas por fecha descendente (más reciente primero).
 *
 * @param ingredientId  Filtrar por ingrediente (opcional)
 */
export async function fetchOrders(ingredientId?: number): Promise<IngredientOrderEntry[]> {
  const query = ingredientId ? `?ingredient_id=${ingredientId}` : "";
  return authenticatedApiFetch<IngredientOrderEntry[]>(`/inventory/orders${query}`);
}