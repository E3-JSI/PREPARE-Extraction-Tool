import { useEffect, useState } from "react";
import Layout from "@components/Layout";
import Button from "@components/Button";
import { usePageTitle } from "@/hooks/usePageTitle";

import {
  getAvailableModels,
  getCurrentModel,
  selectModel,
} from "../../api/settting";
import type { ModelOption } from "../../api/settting";

const Model_Settings = () => {
  usePageTitle("Preferences");

  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] =
    useState<ModelOption | null>(null);

  const [loading, setLoading] = useState(false);

  // ------------------ FETCH AVAILABLE MODELS ------------------
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const data = await getAvailableModels();

        const validModels = data.models.filter((m) => m.id != null);
        setModels(validModels);

        if (validModels.length > 0 && !selectedModel) {
          setSelectedModel(validModels[0]);
        }
      } catch (error) {
        console.error("Failed to fetch models:", error);
      }
    };

    fetchModels();
  }, []);

  // ------------------ FETCH CURRENT MODEL ------------------
  useEffect(() => {
    const fetchCurrent = async () => {
      try { 
        const token = localStorage.getItem("access_token")!;
        const data = await getCurrentModel(token);

        const foundModel = models.find(
          (m) => m.path === data.model_path
        );

        if (foundModel) {
          setSelectedModel(foundModel);
        }
      } catch (error) {
        console.error("Failed to fetch current model:", error);
      }
    };

    if (models.length > 0) {
      fetchCurrent();
    }
  }, [models]);

  // ------------------ SWITCH MODEL ------------------
  const switchModel = async () => {
    if (!selectedModel) return;

    try {
      setLoading(true);

      const token = localStorage.getItem("access_token")!;
      await selectModel(selectedModel.id, token);

      alert(`Switched to ${selectedModel.name}`);
    } catch (error) {
      console.error(error);
      alert("Model switch failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout>
      <h1 style={{ fontSize: 26, fontWeight: 700 }}>
        Model Settings
      </h1>

      <div
        style={{
          background: "#fff",
          padding: 20,
          borderRadius: 12,
          marginTop: 20,
        }}
      >
        <h2>Select Model</h2>

        {/* MODEL DROPDOWN */}
        <select
          style={{
            padding: 10,
            width: 320,
            borderRadius: 8,
            marginTop: 10,
          }}
          value={selectedModel?.path || ""}
          onChange={(e) => {
            const found = models.find(
              (m) => m.path === e.target.value
            );

            if (found) {
              setSelectedModel(found);
            }
          }}
        >
          {models.map((m) => (
            <option key={m.path} value={m.path}>
              {m.name}
            </option>
          ))}
        </select>

        {/* MODEL INFO */}
        {selectedModel && (
          <div style={{ marginTop: 16 }}>
            <p>
              <strong>Engine:</strong> {selectedModel.engine}
            </p>

            <p>
              <strong>Type:</strong> {selectedModel.type}
            </p>

            <p
              style={{
                wordBreak: "break-all",
                fontSize: 13,
                color: "#666",
              }}
            >
              <strong>Path:</strong> {selectedModel.path}
            </p>
          </div>
        )}

        {/* APPLY BUTTON */}
        <div style={{ marginTop: 20 }}>
          <Button onClick={switchModel} disabled={loading}>
            {loading ? "Switching..." : "Apply Model"}
          </Button>
        </div>
      </div>
    </Layout>
  );
};

export default Model_Settings;