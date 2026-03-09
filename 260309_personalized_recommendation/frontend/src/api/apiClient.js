export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";
const apiUrl = new URL(API_BASE_URL);
apiUrl.pathname = apiUrl.pathname.replace(/\/api\/?$/, "") || "/";
export const API_SERVER_URL = `${apiUrl.origin}${apiUrl.pathname === "/" ? "" : apiUrl.pathname}`;

export async function fetchEntities(entityName, limit = 20, offset = 0, filters = {}) {
  const params = new URLSearchParams({ limit, offset });
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.append(key, value);
  });
  const response = await fetch(`${API_BASE_URL}/${entityName}?${params}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${entityName}`);
  }
  return response.json();
}

export async function fetchEntity(entityName, id) {
  const response = await fetch(`${API_BASE_URL}/${entityName}/${id}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${entityName}/${id}`);
  }
  return response.json();
}

export async function fetchFilterOptions() {
  const response = await fetch(`${API_BASE_URL}/articles/filter-options`);
  if (!response.ok) {
    throw new Error("Failed to load filter options");
  }
  return response.json();
}
