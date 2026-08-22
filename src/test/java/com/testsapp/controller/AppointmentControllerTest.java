package com.testsapp.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.testsapp.domain.AppointmentStatus;
import com.testsapp.dto.AppointmentResponse;
import com.testsapp.dto.AvailabilitySlotResponse;
import com.testsapp.dto.CreateAppointmentRequest;
import com.testsapp.dto.DashboardResponse;
import com.testsapp.dto.RescheduleAppointmentRequest;
import com.testsapp.exception.ApiException;
import com.testsapp.service.AppointmentService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.math.BigDecimal;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.temporal.TemporalAdjusters;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.hasSize;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Integration tests for AppointmentController using MockMvc.
 * Tests HTTP requests, response status codes, request/response serialization,
 * and error handling via mocked AppointmentService.
 */
@SpringBootTest
@AutoConfigureMockMvc
class AppointmentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private AppointmentService appointmentService;

    // ─────────────────────────────────────────────────────────────────
    // Helper factories
    // ─────────────────────────────────────────────────────────────────

    /**
     * Returns a LocalDateTime at least 7 days from now on the requested day-of-week
     * at the given hour (minute=0, second=0).
     */
    private static LocalDateTime validFutureSlot(DayOfWeek dow, int hour) {
        LocalDate base = LocalDate.now()
                .plusDays(7)
                .with(TemporalAdjusters.nextOrSame(dow));
        return base.atTime(hour, 0);
    }

    /**
     * Creates a sample AppointmentResponse with given id.
     */
    private AppointmentResponse appointmentResponse(long id, String customerEmail, AppointmentStatus status) {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        return new AppointmentResponse(
                id,
                1L,
                "Haircut",
                "John Doe",
                customerEmail,
                start,
                start.plusMinutes(30),
                status,
                BigDecimal.valueOf(100.00),
                null,
                LocalDateTime.now().minusMinutes(5),
                LocalDateTime.now()
        );
    }

    /**
     * Creates a valid CreateAppointmentRequest.
     */
    private CreateAppointmentRequest createAppointmentRequest(LocalDateTime start, String customerEmail) {
        return new CreateAppointmentRequest(
                1L,
                "John Doe",
                customerEmail,
                start,
                null
        );
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/appointments – list appointments
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("list returns all appointments with 200 OK when no filters provided")
    void testListAppointmentsNoFilters() throws Exception {
        List<AppointmentResponse> appointments = List.of(
                appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED),
                appointmentResponse(2L, "jane@example.com", AppointmentStatus.SCHEDULED),
                appointmentResponse(3L, "bob@example.com", AppointmentStatus.CANCELLED)
        );
        when(appointmentService.listAppointments(null, null)).thenReturn(appointments);

        mockMvc.perform(get("/api/appointments"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(3)))
                .andExpect(jsonPath("$[0].id").value(1))
                .andExpect(jsonPath("$[0].customerEmail").value("john@example.com"))
                .andExpect(jsonPath("$[1].id").value(2))
                .andExpect(jsonPath("$[2].status").value("CANCELLED"));

        verify(appointmentService).listAppointments(null, null);
    }

    @Test
    @DisplayName("list filters by customerEmail parameter")
    void testListAppointmentsByCustomerEmail() throws Exception {
        List<AppointmentResponse> appointments = List.of(
                appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED),
                appointmentResponse(2L, "john@example.com", AppointmentStatus.SCHEDULED)
        );
        when(appointmentService.listAppointments("john@example.com", null)).thenReturn(appointments);

        mockMvc.perform(get("/api/appointments")
                .param("customerEmail", "john@example.com"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].customerEmail").value("john@example.com"))
                .andExpect(jsonPath("$[1].customerEmail").value("john@example.com"));

        verify(appointmentService).listAppointments("john@example.com", null);
    }

    @Test
    @DisplayName("list filters by status parameter")
    void testListAppointmentsByStatus() throws Exception {
        List<AppointmentResponse> appointments = List.of(
                appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED),
                appointmentResponse(2L, "jane@example.com", AppointmentStatus.SCHEDULED)
        );
        when(appointmentService.listAppointments(null, AppointmentStatus.SCHEDULED)).thenReturn(appointments);

        mockMvc.perform(get("/api/appointments")
                .param("status", "SCHEDULED"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].status").value("SCHEDULED"))
                .andExpect(jsonPath("$[1].status").value("SCHEDULED"));

        verify(appointmentService).listAppointments(null, AppointmentStatus.SCHEDULED);
    }

    @Test
    @DisplayName("list applies both customerEmail and status filters")
    void testListAppointmentsWithBothFilters() throws Exception {
        List<AppointmentResponse> appointments = List.of(
                appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED)
        );
        when(appointmentService.listAppointments("john@example.com", AppointmentStatus.SCHEDULED))
                .thenReturn(appointments);

        mockMvc.perform(get("/api/appointments")
                .param("customerEmail", "john@example.com")
                .param("status", "SCHEDULED"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)))
                .andExpect(jsonPath("$[0].customerEmail").value("john@example.com"))
                .andExpect(jsonPath("$[0].status").value("SCHEDULED"));

        verify(appointmentService).listAppointments("john@example.com", AppointmentStatus.SCHEDULED);
    }

    @Test
    @DisplayName("list returns empty array when no appointments match filters")
    void testListAppointmentsEmptyResult() throws Exception {
        when(appointmentService.listAppointments("nonexistent@example.com", null)).thenReturn(List.of());

        mockMvc.perform(get("/api/appointments")
                .param("customerEmail", "nonexistent@example.com"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(0)));
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/appointments/{id} – get appointment by ID
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("getById returns appointment with 200 OK when found")
    void testGetByIdSuccess() throws Exception {
        AppointmentResponse response = appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED);
        when(appointmentService.getById(1L)).thenReturn(response);

        mockMvc.perform(get("/api/appointments/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.customerEmail").value("john@example.com"))
                .andExpect(jsonPath("$.status").value("SCHEDULED"))
                .andExpect(jsonPath("$.serviceName").value("Haircut"));

        verify(appointmentService).getById(1L);
    }

    @Test
    @DisplayName("getById returns 404 NOT_FOUND when appointment does not exist")
    void testGetByIdNotFound() throws Exception {
        when(appointmentService.getById(999L))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono wizyty o id=999"));

        mockMvc.perform(get("/api/appointments/999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status").value(404))
                .andExpect(jsonPath("$.message").value("Nie znaleziono wizyty o id=999"));
    }

    @Test
    @DisplayName("getById rejects non-numeric ID with 400 BAD_REQUEST")
    void testGetByIdInvalidId() throws Exception {
        mockMvc.perform(get("/api/appointments/abc"))
                .andExpect(status().isBadRequest());
    }

    // ─────────────────────────────────────────────────────────────────
    // POST /api/appointments – create appointment
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("create returns 201 CREATED with appointment details on success")
    void testCreateAppointmentSuccess() throws Exception {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        CreateAppointmentRequest request = createAppointmentRequest(start, "john@example.com");
        AppointmentResponse response = appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED);

        when(appointmentService.create(any(CreateAppointmentRequest.class))).thenReturn(response);

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.status").value("SCHEDULED"))
                .andExpect(jsonPath("$.customerEmail").value("john@example.com"));

        verify(appointmentService).create(any(CreateAppointmentRequest.class));
    }

    @Test
    @DisplayName("create returns 400 BAD_REQUEST when request is null")
    void testCreateAppointmentNullRequest() throws Exception {
        when(appointmentService.create(null))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Brak danych wizyty."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("create returns 400 BAD_REQUEST when customer name is blank")
    void testCreateAppointmentBlankName() throws Exception {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        CreateAppointmentRequest request = new CreateAppointmentRequest(
                1L, "   ", "john@example.com", start, null);

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Imie i nazwisko klienta jest wymagane."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Imie i nazwisko klienta jest wymagane."));
    }

    @Test
    @DisplayName("create returns 400 BAD_REQUEST when email is invalid")
    void testCreateAppointmentInvalidEmail() throws Exception {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        CreateAppointmentRequest request = new CreateAppointmentRequest(
                1L, "John Doe", "invalidexample.com", start, null);

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Poprawny e-mail klienta jest wymagany."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").contains("e-mail"));
    }

    @Test
    @DisplayName("create returns 400 BAD_REQUEST when start time is null")
    void testCreateAppointmentNullStartTime() throws Exception {
        CreateAppointmentRequest request = new CreateAppointmentRequest(
                1L, "John Doe", "john@example.com", null, null);

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Termin wizyty jest wymagany."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("create returns 400 BAD_REQUEST when start time not aligned to 15-minute intervals")
    void testCreateAppointmentMisalignedTime() throws Exception {
        LocalDateTime misaligned = LocalDateTime.of(2026, 9, 1, 14, 5, 0);
        CreateAppointmentRequest request = createAppointmentRequest(misaligned, "john@example.com");

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Termin musi zaczynac sie co 15 minut."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("create returns 409 CONFLICT when insufficient notice (< 2 hours)")
    void testCreateAppointmentInsufficientNotice() throws Exception {
        LocalDateTime tooSoon = LocalDateTime.now().plusMinutes(60);
        CreateAppointmentRequest request = createAppointmentRequest(tooSoon, "john@example.com");

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Rezerwacja wymaga co najmniej 2 godzin wyprzedzenia."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.status").value(409));
    }

    @Test
    @DisplayName("create returns 409 CONFLICT when appointment > 90 days in future")
    void testCreateAppointmentBeyondPlanningWindow() throws Exception {
        LocalDateTime farFuture = LocalDate.now().plusDays(92).atTime(10, 0);
        CreateAppointmentRequest request = createAppointmentRequest(farFuture, "john@example.com");

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Wizyte mozna zaplanowac maksymalnie 90 dni do przodu."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    @Test
    @DisplayName("create returns 409 CONFLICT when appointment outside business hours")
    void testCreateAppointmentOutsideHours() throws Exception {
        LocalDateTime outside = LocalDate.now().plusDays(10).atTime(18, 0);
        CreateAppointmentRequest request = createAppointmentRequest(outside, "john@example.com");

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Wizyta musi miescic sie w godzinach 09:00-17:00."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    @Test
    @DisplayName("create returns 409 CONFLICT when customer has max future appointments")
    void testCreateAppointmentMaxBookingsExceeded() throws Exception {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        CreateAppointmentRequest request = createAppointmentRequest(start, "john@example.com");

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Klient ma juz maksymalna liczbe przyszlych wizyt."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    @Test
    @DisplayName("create returns 409 CONFLICT when time slot conflicts with existing appointment")
    void testCreateAppointmentTimeConflict() throws Exception {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        CreateAppointmentRequest request = createAppointmentRequest(start, "john@example.com");

        when(appointmentService.create(any()))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Wybrany termin jest juz zajety."));

        mockMvc.perform(post("/api/appointments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.message").value("Wybrany termin jest juz zajety."));
    }

    // ─────────────────────────────────────────────────────────────────
    // POST /api/appointments/{id}/cancel – cancel appointment
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("cancel returns 200 OK with cancelled appointment on success")
    void testCancelAppointmentSuccess() throws Exception {
        AppointmentResponse response = appointmentResponse(1L, "john@example.com", AppointmentStatus.CANCELLED);
        when(appointmentService.cancel(1L)).thenReturn(response);

        mockMvc.perform(post("/api/appointments/1/cancel"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.status").value("CANCELLED"));

        verify(appointmentService).cancel(1L);
    }

    @Test
    @DisplayName("cancel returns 404 NOT_FOUND when appointment does not exist")
    void testCancelAppointmentNotFound() throws Exception {
        when(appointmentService.cancel(999L))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono wizyty o id=999"));

        mockMvc.perform(post("/api/appointments/999/cancel"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("cancel returns 409 CONFLICT when appointment is not SCHEDULED")
    void testCancelAppointmentNotScheduled() throws Exception {
        when(appointmentService.cancel(1L))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Tylko zaplanowana wizyte mozna anulowac."));

        mockMvc.perform(post("/api/appointments/1/cancel"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.message").value("Tylko zaplanowana wizyte mozna anulowac."));
    }

    @Test
    @DisplayName("cancel returns 409 CONFLICT when trying to cancel too close to start time")
    void testCancelAppointmentTooLate() throws Exception {
        when(appointmentService.cancel(1L))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Nie mozna anulowac wizyty pozniej niz godzine przed terminem."));

        mockMvc.perform(post("/api/appointments/1/cancel"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.message").contains("godzine"));
    }

    // ─────────────────────────────────────────────────────────────────
    // POST /api/appointments/{id}/reschedule – reschedule appointment
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("reschedule returns 200 OK with updated appointment on success")
    void testRescheduleAppointmentSuccess() throws Exception {
        LocalDateTime newTime = validFutureSlot(DayOfWeek.WEDNESDAY, 10);
        RescheduleAppointmentRequest request = new RescheduleAppointmentRequest(newTime);
        AppointmentResponse response = appointmentResponse(1L, "john@example.com", AppointmentStatus.SCHEDULED);

        when(appointmentService.reschedule(1L, request)).thenReturn(response);

        mockMvc.perform(post("/api/appointments/1/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(1))
                .andExpect(jsonPath("$.status").value("SCHEDULED"));

        verify(appointmentService).reschedule(1L, request);
    }

    @Test
    @DisplayName("reschedule returns 400 BAD_REQUEST when request is null")
    void testRescheduleAppointmentNullRequest() throws Exception {
        when(appointmentService.reschedule(eq(1L), any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Nowy termin jest wymagany."));

        mockMvc.perform(post("/api/appointments/1/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("reschedule returns 400 BAD_REQUEST when new start time is null")
    void testRescheduleAppointmentNullNewTime() throws Exception {
        RescheduleAppointmentRequest request = new RescheduleAppointmentRequest(null);

        when(appointmentService.reschedule(eq(1L), any()))
                .thenThrow(new ApiException(HttpStatus.BAD_REQUEST, "Nowy termin jest wymagany."));

        mockMvc.perform(post("/api/appointments/1/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").value("Nowy termin jest wymagany."));
    }

    @Test
    @DisplayName("reschedule returns 404 NOT_FOUND when appointment does not exist")
    void testRescheduleAppointmentNotFound() throws Exception {
        LocalDateTime newTime = validFutureSlot(DayOfWeek.WEDNESDAY, 10);
        RescheduleAppointmentRequest request = new RescheduleAppointmentRequest(newTime);

        when(appointmentService.reschedule(999L, request))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono wizyty o id=999"));

        mockMvc.perform(post("/api/appointments/999/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("reschedule returns 409 CONFLICT when appointment is not SCHEDULED")
    void testRescheduleAppointmentNotScheduled() throws Exception {
        LocalDateTime newTime = validFutureSlot(DayOfWeek.WEDNESDAY, 10);
        RescheduleAppointmentRequest request = new RescheduleAppointmentRequest(newTime);

        when(appointmentService.reschedule(1L, request))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Mozna przelozyc tylko zaplanowana wizyte."));

        mockMvc.perform(post("/api/appointments/1/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    @Test
    @DisplayName("reschedule returns 409 CONFLICT when appointment is too close to start time")
    void testRescheduleAppointmentTooLate() throws Exception {
        LocalDateTime newTime = validFutureSlot(DayOfWeek.WEDNESDAY, 10);
        RescheduleAppointmentRequest request = new RescheduleAppointmentRequest(newTime);

        when(appointmentService.reschedule(1L, request))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Wizyty bliskiej terminu nie mozna przelozyc."));

        mockMvc.perform(post("/api/appointments/1/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    @Test
    @DisplayName("reschedule returns 409 CONFLICT when new time has conflict with existing appointment")
    void testRescheduleAppointmentTimeConflict() throws Exception {
        LocalDateTime newTime = validFutureSlot(DayOfWeek.WEDNESDAY, 10);
        RescheduleAppointmentRequest request = new RescheduleAppointmentRequest(newTime);

        when(appointmentService.reschedule(1L, request))
                .thenThrow(new ApiException(HttpStatus.CONFLICT, "Wybrany termin jest juz zajety."));

        mockMvc.perform(post("/api/appointments/1/reschedule")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isConflict());
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/appointments/availability – get available slots
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("availability returns list of available slots with 200 OK")
    void testAvailabilitySuccess() throws Exception {
        LocalDate futureDate = LocalDate.now().plusDays(10);
        AvailabilitySlotResponse slot1 = new AvailabilitySlotResponse(
                futureDate.atTime(9, 0),
                futureDate.atTime(9, 30),
                true,
                null
        );
        AvailabilitySlotResponse slot2 = new AvailabilitySlotResponse(
                futureDate.atTime(9, 15),
                futureDate.atTime(9, 45),
                true,
                null
        );
        List<AvailabilitySlotResponse> slots = List.of(slot1, slot2);

        when(appointmentService.availability(1L, futureDate)).thenReturn(slots);

        mockMvc.perform(get("/api/appointments/availability")
                .param("serviceOfferId", "1")
                .param("date", futureDate.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].available").value(true))
                .andExpect(jsonPath("$[0].reason").doesNotExist())
                .andExpect(jsonPath("$[1].available").value(true));

        verify(appointmentService).availability(1L, futureDate);
    }

    @Test
    @DisplayName("availability returns slots for today when date parameter not provided")
    void testAvailabilityWithoutDateParameter() throws Exception {
        LocalDate today = LocalDate.now();
        List<AvailabilitySlotResponse> slots = List.of(
                new AvailabilitySlotResponse(
                        today.atTime(9, 0),
                        today.atTime(9, 30),
                        false,
                        "za malo czasu na rezerwacje dzisiejsza"
                )
        );

        when(appointmentService.availability(1L, null)).thenReturn(slots);

        mockMvc.perform(get("/api/appointments/availability")
                .param("serviceOfferId", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)))
                .andExpect(jsonPath("$[0].available").value(false));

        verify(appointmentService).availability(1L, null);
    }

    @Test
    @DisplayName("availability includes unavailable slots with reason")
    void testAvailabilityWithUnavailableSlots() throws Exception {
        LocalDate futureDate = LocalDate.now().plusDays(10);
        AvailabilitySlotResponse available = new AvailabilitySlotResponse(
                futureDate.atTime(9, 0),
                futureDate.atTime(9, 30),
                true,
                null
        );
        AvailabilitySlotResponse unavailable = new AvailabilitySlotResponse(
                futureDate.atTime(14, 0),
                futureDate.atTime(14, 30),
                false,
                "termin zajety"
        );
        List<AvailabilitySlotResponse> slots = List.of(available, unavailable);

        when(appointmentService.availability(1L, futureDate)).thenReturn(slots);

        mockMvc.perform(get("/api/appointments/availability")
                .param("serviceOfferId", "1")
                .param("date", futureDate.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].available").value(true))
                .andExpect(jsonPath("$[1].available").value(false))
                .andExpect(jsonPath("$[1].reason").value("termin zajety"));
    }

    @Test
    @DisplayName("availability returns 404 NOT_FOUND when service does not exist")
    void testAvailabilityServiceNotFound() throws Exception {
        LocalDate futureDate = LocalDate.now().plusDays(10);

        when(appointmentService.availability(999L, futureDate))
                .thenThrow(new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono aktywnej uslugi o id=999"));

        mockMvc.perform(get("/api/appointments/availability")
                .param("serviceOfferId", "999")
                .param("date", futureDate.toString()))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("availability requires serviceOfferId parameter")
    void testAvailabilityMissingServiceOfferId() throws Exception {
        mockMvc.perform(get("/api/appointments/availability"))
                .andExpect(status().isBadRequest());
    }

    // ─────────────────────────────────────────────────────────────────
    // GET /api/appointments/dashboard – get dashboard
    // ─────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("dashboard returns 200 OK with appointment statistics")
    void testDashboardSuccess() throws Exception {
        Map<AppointmentStatus, Long> statusCounts = Map.of(
                AppointmentStatus.SCHEDULED, 5L,
                AppointmentStatus.CANCELLED, 2L,
                AppointmentStatus.COMPLETED, 3L
        );
        LocalDateTime nextAppointment = validFutureSlot(DayOfWeek.TUESDAY, 14);
        DashboardResponse dashboard = new DashboardResponse(
                3,  // totalServices
                10, // totalAppointments
                statusCounts,
                BigDecimal.valueOf(500.00),  // projectedRevenue
                BigDecimal.valueOf(250.00),  // realizedRevenue
                nextAppointment
        );

        when(appointmentService.dashboard()).thenReturn(dashboard);

        mockMvc.perform(get("/api/appointments/dashboard"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalServices").value(3))
                .andExpect(jsonPath("$.totalAppointments").value(10))
                .andExpect(jsonPath("$.countsByStatus.SCHEDULED").value(5))
                .andExpect(jsonPath("$.countsByStatus.CANCELLED").value(2))
                .andExpect(jsonPath("$.countsByStatus.COMPLETED").value(3))
                .andExpect(jsonPath("$.projectedRevenue").value(500.00))
                .andExpect(jsonPath("$.realizedRevenue").value(250.00));

        verify(appointmentService).dashboard();
    }

    @Test
    @DisplayName("dashboard returns zero values when no appointments exist")
    void testDashboardEmpty() throws Exception {
        Map<AppointmentStatus, Long> statusCounts = Map.of(
                AppointmentStatus.SCHEDULED, 0L,
                AppointmentStatus.CANCELLED, 0L,
                AppointmentStatus.COMPLETED, 0L
        );
        DashboardResponse dashboard = new DashboardResponse(
                0,  // totalServices
                0,  // totalAppointments
                statusCounts,
                BigDecimal.ZERO,
                BigDecimal.ZERO,
                null
        );

        when(appointmentService.dashboard()).thenReturn(dashboard);

        mockMvc.perform(get("/api/appointments/dashboard"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalServices").value(0))
                .andExpect(jsonPath("$.totalAppointments").value(0))
                .andExpect(jsonPath("$.projectedRevenue").value(0))
                .andExpect(jsonPath("$.realizedRevenue").value(0))
                .andExpect(jsonPath("$.nextAppointmentStart").doesNotExist());
    }

    @Test
    @DisplayName("dashboard includes nextAppointmentStart when appointments exist")
    void testDashboardWithNextAppointment() throws Exception {
        Map<AppointmentStatus, Long> statusCounts = Map.of(
                AppointmentStatus.SCHEDULED, 3L,
                AppointmentStatus.CANCELLED, 0L,
                AppointmentStatus.COMPLETED, 0L
        );
        LocalDateTime nextAppointment = validFutureSlot(DayOfWeek.TUESDAY, 14);
        DashboardResponse dashboard = new DashboardResponse(
                2,
                3,
                statusCounts,
                BigDecimal.valueOf(300.00),
                BigDecimal.ZERO,
                nextAppointment
        );

        when(appointmentService.dashboard()).thenReturn(dashboard);

        mockMvc.perform(get("/api/appointments/dashboard"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.nextAppointmentStart").exists())
                .andExpect(jsonPath("$.countsByStatus.SCHEDULED").value(3));
    }
}

