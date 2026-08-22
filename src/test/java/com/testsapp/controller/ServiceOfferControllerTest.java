package com.testsapp.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.testsapp.dto.CreateServiceOfferRequest;
import com.testsapp.dto.ServiceOfferResponse;
import com.testsapp.exception.ApiException;
import com.testsapp.service.ServiceOfferService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Integration tests for ServiceOfferController using MockMvc.
 * Tests HTTP requests, response status codes, request/response serialization,
 * and error handling via mocked ServiceOfferService.
 */
@SpringBootTest
@AutoConfigureMockMvc
class ServiceOfferControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private ServiceOfferService serviceOfferService;

    // ─────────────────────────────────────────────────────────────────
    // Helper factories
    // ─────────────────────────────────────────────────────────────────

    /**
     * Creates a sample ServiceOfferResponse with given parameters.
     */
    private ServiceOfferResponse serviceOfferResponse(long id, String name, int durationMinutes,
                                                      BigDecimal basePrice, boolean active) {
        LocalDateTime now = LocalDateTime.now();
        return new ServiceOfferResponse(
                id,
                name,
                durationMinutes,
                basePrice,
                active,
                now.minusMinutes(10),
                now
        );
    }

    /**
     * Creates a valid CreateServiceOfferRequest.
     */
    private CreateServiceOfferRequest createServiceOfferRequest(String name, int durationMinutes,
                                                                 BigDecimal basePrice) {
        return new CreateServiceOfferRequest(name, durationMinutes, basePrice);
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/service-offers – list all service offers
    // ─────────────────────────────────────────────────────────────────

    // AI GENERATED
    @Test
    @DisplayName("list returns all service offers with 200 OK")
    void testListAllServiceOffers() throws Exception {
        List<ServiceOfferResponse> offers = List.of(
                serviceOfferResponse(1L, "Haircut", 30, BigDecimal.valueOf(50.00), true),
                serviceOfferResponse(2L, "Hair Coloring", 60, BigDecimal.valueOf(100.00), true),
                serviceOfferResponse(3L, "Beard Trim", 20, BigDecimal.valueOf(25.00), false)
        );
        when(serviceOfferService.listAll()).thenReturn(offers);

        mockMvc.perform(get("/api/service-offers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(3)))
                .andExpect(jsonPath("$[0].id").value(1))
                .andExpect(jsonPath("$[0].name").value("Haircut"))
                .andExpect(jsonPath("$[0].durationMinutes").value(30))
                .andExpect(jsonPath("$[0].basePrice").value(50.00))
                .andExpect(jsonPath("$[0].active").value(true))
                .andExpect(jsonPath("$[1].id").value(2))
                .andExpect(jsonPath("$[2].active").value(false));

        verify(serviceOfferService).listAll();
    }

    // AI GENERATED
    @Test
    @DisplayName("list returns empty array when no service offers exist")
    void testListAllServiceOffersEmpty() throws Exception {
        when(serviceOfferService.listAll()).thenReturn(List.of());

        mockMvc.perform(get("/api/service-offers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(0)));

        verify(serviceOfferService).listAll();
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/service-offers/active – list only active offers
    // ─────────────────────────────────────────────────────────────────

    // AI GENERATED
    @Test
    @DisplayName("listActive returns only active service offers with 200 OK")
    void testListActiveServiceOffers() throws Exception {
        List<ServiceOfferResponse> activeOffers = List.of(
                serviceOfferResponse(1L, "Haircut", 30, BigDecimal.valueOf(50.00), true),
                serviceOfferResponse(2L, "Hair Coloring", 60, BigDecimal.valueOf(100.00), true)
        );
        when(serviceOfferService.listActive()).thenReturn(activeOffers);

        mockMvc.perform(get("/api/service-offers/active"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].active").value(true))
                .andExpect(jsonPath("$[1].active").value(true))
                .andExpect(jsonPath("$[0].name").value("Haircut"))
                .andExpect(jsonPath("$[1].name").value("Hair Coloring"));

        verify(serviceOfferService).listActive();
    }

    // AI GENERATED
    @Test
    @DisplayName("listActive returns empty array when no active offers exist")
    void testListActiveServiceOffersEmpty() throws Exception {
        when(serviceOfferService.listActive()).thenReturn(List.of());

        mockMvc.perform(get("/api/service-offers/active"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(0)));

        verify(serviceOfferService).listActive();
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/service-offers/{id} – get specific offer by ID
    // ─────────────────────────────────────────────────────────────────

    // AI GENERATED
    @Test
    @DisplayName("getById returns service offer with 200 OK when found")
    void testGetByIdSuccess() throws Exception {
        ServiceOfferResponse response = serviceOfferResponse(1L, "Haircut", 30, BigDecimal.valueOf(50.00), true);
        when(serviceOfferService.getById(1L)).thenReturn(response);

        mockMvc.perform(get("/api/service-offers/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.name").value("Haircut"))
                .andExpect(jsonPath("$.durationMinutes").value(30))
                .andExpect(jsonPath("$.basePrice").value(50.00))
                .andExpect(jsonPath("$.active").value(true));

        verify(serviceOfferService).getById(1L);
    }

    // AI GENERATED
    @Test
    @DisplayName("getById returns 404 NOT_FOUND when service offer does not exist")
    void testGetByIdNotFound() throws Exception {
        when(serviceOfferService.getById(999L))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono usługi o id=999"));

        mockMvc.perform(get("/api/service-offers/999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status").value(404))
                .andExpect(jsonPath("$.message").value("Nie znaleziono usługi o id=999"));

        verify(serviceOfferService).getById(999L);
    }

    // AI GENERATED
    @Test
    @DisplayName("getById rejects non-numeric ID with 400 BAD_REQUEST")
    void testGetByIdInvalidId() throws Exception {
        mockMvc.perform(get("/api/service-offers/abc"))
                .andExpect(status().isBadRequest());
    }

    // ─────────────────────────────────────────────────────────────────
    // POST /api/service-offers – create new offer
    // ─────────────────────────────────────────────────────────────────

    // AI GENERATED
    @Test
    @DisplayName("create returns 201 CREATED with service offer details on success")
    void testCreateServiceOfferSuccess() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 30, BigDecimal.valueOf(50.00));
        ServiceOfferResponse response = serviceOfferResponse(1L, "Haircut", 30, BigDecimal.valueOf(50.00), true);

        when(serviceOfferService.create(any(CreateServiceOfferRequest.class))).thenReturn(response);

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.name").value("Haircut"))
                .andExpect(jsonPath("$.durationMinutes").value(30))
                .andExpect(jsonPath("$.basePrice").value(50.00))
                .andExpect(jsonPath("$.active").value(true));

        verify(serviceOfferService).create(any(CreateServiceOfferRequest.class));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when request is null")
    void testCreateServiceOfferNullRequest() throws Exception {
        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Brak danych usługi."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Brak danych usługi."));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when service name is blank")
    void testCreateServiceOfferBlankName() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("   ", 30, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Nazwa usługi jest wymagana."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Nazwa usługi jest wymagana."));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when name is null")
    void testCreateServiceOfferNullName() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest(null, 30, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Nazwa usługi jest wymagana."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("Nazwa usługi"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when duration is less than 15 minutes")
    void testCreateServiceOfferDurationTooShort() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 10, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Czas trwania musi byc wielokrotnoscia 15 minut, w zakresie 15-240."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("Czas trwania"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when duration exceeds 240 minutes")
    void testCreateServiceOfferDurationTooLong() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 300, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Czas trwania musi byc wielokrotnoscia 15 minut, w zakresie 15-240."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("15-240"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when duration is not multiple of 15 minutes")
    void testCreateServiceOfferDurationNotMultiple() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 25, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Czas trwania musi byc wielokrotnoscia 15 minut, w zakresie 15-240."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("wielokrotnoscia"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when base price is null")
    void testCreateServiceOfferNullPrice() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 30, null);

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Cena bazowa musi byc wieksza od zera."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("Cena"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when base price is zero")
    void testCreateServiceOfferZeroPrice() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 30, BigDecimal.ZERO);

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Cena bazowa musi byc wieksza od zera."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("wieksza"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 400 BAD_REQUEST when base price is negative")
    void testCreateServiceOfferNegativePrice() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 30, BigDecimal.valueOf(-10.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Cena bazowa musi byc wieksza od zera."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("zera"));
    }

    // AI GENERATED
    @Test
    @DisplayName("create returns 409 CONFLICT when service with same name already exists")
    void testCreateServiceOfferDuplicateName() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("Haircut", 30, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Usługa o takiej nazwie już istnieje."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.status").value(409))
                .andExpect(jsonPath("$.message").value("Usługa o takiej nazwie już istnieje."));
    }

    // AI GENERATED
    @Test
    @DisplayName("create is case-insensitive when checking for duplicate names")
    void testCreateServiceOfferDuplicateNameCaseInsensitive() throws Exception {
        CreateServiceOfferRequest request = createServiceOfferRequest("HAIRCUT", 30, BigDecimal.valueOf(50.00));

        when(serviceOfferService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Usługa o takiej nazwie już istnieje."));

        mockMvc.perform(post("/api/service-offers")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    // ─────────────────────────────────────────────────────────────────
    // PATCH /api/service-offers/{id}/activate – activate an offer
    // ─────────────────────────────────────────────────────────────────

    // AI GENERATED
    @Test
    @DisplayName("activate returns 200 OK with activated service offer on success")
    void testActivateServiceOfferSuccess() throws Exception {
        ServiceOfferResponse response = serviceOfferResponse(1L, "Haircut", 30, BigDecimal.valueOf(50.00), true);
        when(serviceOfferService.activate(1L)).thenReturn(response);

        mockMvc.perform(patch("/api/service-offers/1/activate"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.active").value(true))
                .andExpect(jsonPath("$.name").value("Haircut"));

        verify(serviceOfferService).activate(1L);
    }

    // AI GENERATED
    @Test
    @DisplayName("activate returns 404 NOT_FOUND when service offer does not exist")
    void testActivateServiceOfferNotFound() throws Exception {
        when(serviceOfferService.activate(999L))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono usługi o id=999"));

        mockMvc.perform(patch("/api/service-offers/999/activate"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status").value(404));

        verify(serviceOfferService).activate(999L);
    }

    // AI GENERATED
    @Test
    @DisplayName("activate rejects non-numeric ID with 400 BAD_REQUEST")
    void testActivateServiceOfferInvalidId() throws Exception {
        mockMvc.perform(patch("/api/service-offers/abc/activate"))
                .andExpect(status().isBadRequest());
    }

    // ─────────────────────────────────────────────────────────────────
    // PATCH /api/service-offers/{id}/deactivate – deactivate an offer
    // ─────────────────────────────────────────────────────────────────

    // AI GENERATED
    @Test
    @DisplayName("deactivate returns 200 OK with deactivated service offer on success")
    void testDeactivateServiceOfferSuccess() throws Exception {
        ServiceOfferResponse response = serviceOfferResponse(1L, "Haircut", 30, BigDecimal.valueOf(50.00), false);
        when(serviceOfferService.deactivate(1L)).thenReturn(response);

        mockMvc.perform(patch("/api/service-offers/1/deactivate"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.active").value(false))
                .andExpect(jsonPath("$.name").value("Haircut"));

        verify(serviceOfferService).deactivate(1L);
    }

    // AI GENERATED
    @Test
    @DisplayName("deactivate returns 404 NOT_FOUND when service offer does not exist")
    void testDeactivateServiceOfferNotFound() throws Exception {
        when(serviceOfferService.deactivate(999L))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono usługi o id=999"));

        mockMvc.perform(patch("/api/service-offers/999/deactivate"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status").value(404));

        verify(serviceOfferService).deactivate(999L);
    }

    // AI GENERATED
    @Test
    @DisplayName("deactivate returns 409 CONFLICT when service has active future appointments")
    void testDeactivateServiceOfferWithActiveAppointments() throws Exception {
        when(serviceOfferService.deactivate(1L))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Nie można wyłączyć usługi z aktywnymi przyszłymi wizytami."));

        mockMvc.perform(patch("/api/service-offers/1/deactivate"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.status").value(409))
                .andExpect(jsonPath("$.message").value("Nie można wyłączyć usługi z aktywnymi przyszłymi wizytami."));

        verify(serviceOfferService).deactivate(1L);
    }

    // AI GENERATED
    @Test
    @DisplayName("deactivate rejects non-numeric ID with 400 BAD_REQUEST")
    void testDeactivateServiceOfferInvalidId() throws Exception {
        mockMvc.perform(patch("/api/service-offers/abc/deactivate"))
                .andExpect(status().isBadRequest());
    }
}

