export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";
const apiUrl = new URL(API_BASE_URL);
apiUrl.pathname = apiUrl.pathname.replace(/\/api\/?$/, "") || "/";
export const API_SERVER_URL = `${apiUrl.origin}${apiUrl.pathname === "/" ? "" : apiUrl.pathname}`;

export async function fetchEntities(entityName, limit = 20, offset = 0) {
  const response = await fetch(`${API_BASE_URL}/${entityName}?limit=${limit}&offset=${offset}`);
  if (!response.ok) {
    throw new Error(`Failed to load ${entityName}`);
  }
  return response.json();
}
