package com.testsapp.service;

import com.testsapp.domain.Appointment;
import com.testsapp.domain.AppointmentStatus;
import com.testsapp.domain.ServiceOffer;
import com.testsapp.dto.AppointmentResponse;
import com.testsapp.dto.AvailabilitySlotResponse;
import com.testsapp.dto.CreateAppointmentRequest;
import com.testsapp.dto.DashboardResponse;
import com.testsapp.dto.RescheduleAppointmentRequest;
import com.testsapp.exception.ApiException;
import com.testsapp.repository.AppointmentRepository;
import com.testsapp.repository.ServiceOfferRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;

import java.math.BigDecimal;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Characterization tests for AppointmentService (legacy mode, plan-v1).
 *
 * Repositories are MOCKED with Mockito; domain objects are constructed as real instances.
 * Times that must satisfy notice/window guards are constructed relative to
 * LocalDateTime.now() so tests remain deterministic across days.
 */
@ExtendWith(MockitoExtension.class)
class AppointmentServiceTest {

    @Mock
    AppointmentRepository appointmentRepository;

    @Mock
    ServiceOfferRepository serviceOfferRepository;

    @Mock
    NotificationService notificationService;

    @InjectMocks
    AppointmentService appointmentService;

    // ─────────────────────────────────────────────────────────────────
    // Helper factories
    // ─────────────────────────────────────────────────────────────────

    /**
     * Returns a LocalDateTime at least 7 days from now on the requested day-of-week
     * at the given hour (minute=0, second=0). Always within the 2h-90d booking window
     * and within business hours 09-17 (assuming hour in [9, 16] for 30-min slots).
     */
    private static LocalDateTime validFutureSlot(DayOfWeek dow, int hour) {
        LocalDate base = LocalDate.now()
                .plusDays(7)
                .with(TemporalAdjusters.nextOrSame(dow));
        return base.atTime(hour, 0);
    }

    /**
     * Returns a slot ~90 minutes from now, aligned DOWN to the 15-minute grid.
     * Guaranteed: now+75min ≤ result ≤ now+90min → always < 2 hours from now.
     */
    private static LocalDateTime slotWithinTwoHours() {
        LocalDateTime base = LocalDateTime.now().plusMinutes(90);
        int aligned = (base.getMinute() / 15) * 15;
        return base.withSecond(0).withNano(0).withMinute(aligned);
    }

    /**
     * Returns a slot ~30 minutes from now, aligned DOWN to the 15-minute grid.
     * Guaranteed: now+15min ≤ result ≤ now+30min → always < 1 hour from now.
     */
    private static LocalDateTime slotWithinOneHour() {
        LocalDateTime base = LocalDateTime.now().plusMinutes(30);
        int aligned = (base.getMinute() / 15) * 15;
        return base.withSecond(0).withNano(0).withMinute(aligned);
    }

    /** Creates an active ServiceOffer with id=1. */
    private ServiceOffer activeOffer(int durationMinutes, BigDecimal basePrice) {
        ServiceOffer offer = new ServiceOffer("Haircut", durationMinutes, basePrice, true);
        offer.assignId(1L);
        return offer;
    }

    /** Creates a SCHEDULED Appointment with the given id and start/duration. */
    private Appointment scheduledAppointment(long id, LocalDateTime start, int durationMinutes) {
        Appointment a = new Appointment(
                1L, "Haircut", "John Doe", "john@example.com",
                start, start.plusMinutes(durationMinutes),
                BigDecimal.valueOf(100), null);
        a.assignId(id);
        return a;
    }

    /** Minimal valid CreateAppointmentRequest pointing at serviceOffer id=1. */
    private static CreateAppointmentRequest validRequest(LocalDateTime start) {
        return new CreateAppointmentRequest(1L, "John Doe", "john@example.com", start, null);
    }

    // ─────────────────────────────────────────────────────────────────
    // TC01 – TC04 · listAppointments
    // ─────────────────────────────────────────────────────────────────

    // TC01
    @Test
    @DisplayName("listAppointments returns all appointments when no filters provided")
    void testListAppointmentsWithoutFilters() {
        LocalDateTime t = validFutureSlot(DayOfWeek.TUESDAY, 14);
        when(appointmentRepository.findAll()).thenReturn(List.of(
                scheduledAppointment(1L, t, 30),
                scheduledAppointment(2L, t.plusHours(1), 30),
                scheduledAppointment(3L, t.plusHours(2), 30)
        ));

        List<AppointmentResponse> result = appointmentService.listAppointments(null, null);

        assertThat(result).hasSize(3);
    }

    // TC02
    @Test
    @DisplayName("listAppointments filters by customer email (case-insensitive)")
    void testListAppointmentsByCustomerEmail() {
        LocalDateTime t = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment john1 = scheduledAppointment(1L, t, 30);
        Appointment john2 = scheduledAppointment(2L, t.plusHours(2), 30);
        Appointment jane = new Appointment(
                1L, "Massage", "Jane Smith", "jane@example.com",
                t.plusHours(1), t.plusHours(1).plusMinutes(30),
                BigDecimal.valueOf(80), null);
        jane.assignId(3L);

        when(appointmentRepository.findAll()).thenReturn(List.of(john1, jane, john2));

        List<AppointmentResponse> result =
                appointmentService.listAppointments("JOHN@EXAMPLE.COM", null);

        assertThat(result).hasSize(2)
                .allMatch(r -> r.customerEmail().equalsIgnoreCase("john@example.com"));
    }

    // TC03
    @Test
    @DisplayName("listAppointments filters by appointment status")
    void testListAppointmentsByStatus() {
        LocalDateTime t = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment scheduled = scheduledAppointment(1L, t, 30);
        Appointment cancelled = scheduledAppointment(2L, t.plusHours(1), 30);
        cancelled.cancel();

        when(appointmentRepository.findAll()).thenReturn(List.of(scheduled, cancelled));

        List<AppointmentResponse> result =
                appointmentService.listAppointments(null, AppointmentStatus.SCHEDULED);

        assertThat(result).hasSize(1)
                .allMatch(r -> r.status() == AppointmentStatus.SCHEDULED);
    }

    // TC04
    @Test
    @DisplayName("listAppointments applies both customerEmail and status filters together")
    void testListAppointmentsWithBothFilters() {
        LocalDateTime t = validFutureSlot(DayOfWeek.TUESDAY, 14);

        Appointment matchBoth = new Appointment(
                1L, "H", "Cust", "customer@test.com",
                t, t.plusMinutes(30), BigDecimal.TEN, null);
        matchBoth.assignId(1L);
        matchBoth.cancel();

        Appointment wrongEmail = scheduledAppointment(2L, t.plusHours(1), 30); // john@example.com
        wrongEmail.cancel();

        Appointment wrongStatus = new Appointment(
                1L, "H", "Cust", "customer@test.com",
                t.plusHours(2), t.plusHours(2).plusMinutes(30), BigDecimal.TEN, null);
        wrongStatus.assignId(3L); // SCHEDULED

        when(appointmentRepository.findAll()).thenReturn(List.of(matchBoth, wrongEmail, wrongStatus));

        List<AppointmentResponse> result =
                appointmentService.listAppointments("customer@test.com", AppointmentStatus.CANCELLED);

        assertThat(result).hasSize(1)
                .allMatch(r -> r.customerEmail().equalsIgnoreCase("customer@test.com")
                        && r.status() == AppointmentStatus.CANCELLED);
    }

    // ─────────────────────────────────────────────────────────────────
    // TC05 – TC06 · getById
    // ─────────────────────────────────────────────────────────────────

    // TC05
    @Test
    @DisplayName("getById returns appointment response when appointment exists")
    void testGetByIdFound() {
        LocalDateTime t = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment a = scheduledAppointment(1L, t, 30);
        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));

        AppointmentResponse result = appointmentService.getById(1L);

        assertThat(result.id()).isEqualTo(1L);
        assertThat(result.customerEmail()).isEqualTo("john@example.com");
        assertThat(result.status()).isEqualTo(AppointmentStatus.SCHEDULED);
    }

    // TC06
    @Test
    @DisplayName("getById throws ApiException with NOT_FOUND status when appointment not found")
    void testGetByIdNotFound() {
        when(appointmentRepository.findById(999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> appointmentService.getById(999L))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.NOT_FOUND));
    }

    // ─────────────────────────────────────────────────────────────────
    // TC07 – TC24 · create
    // ─────────────────────────────────────────────────────────────────

    // TC07
    @Test
    @DisplayName("create appointment successfully when all validation rules pass")
    void testCreateAppointmentSuccess() {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        ServiceOffer offer = activeOffer(30, BigDecimal.valueOf(100));

        when(serviceOfferRepository.findById(1L)).thenReturn(Optional.of(offer));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of());
        when(appointmentRepository.findAll()).thenReturn(List.of());
        when(appointmentRepository.save(any())).thenAnswer(inv -> {
            Appointment a = inv.getArgument(0);
            a.assignId(1L);
            return a;
        });

        AppointmentResponse result = appointmentService.create(validRequest(start));

        assertThat(result).isNotNull();
        assertThat(result.status()).isEqualTo(AppointmentStatus.SCHEDULED);
        assertThat(result.customerEmail()).isEqualTo("john@example.com");
    }

    // TC08
    @Test
    @DisplayName("create rejects null request with BAD_REQUEST status")
    void testCreateNullRequest() {
        assertThatThrownBy(() -> appointmentService.create(null))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC09
    @Test
    @DisplayName("create rejects blank or null customer name")
    void testCreateBlankName() {
        CreateAppointmentRequest req = new CreateAppointmentRequest(
                1L, "   ", "john@example.com",
                validFutureSlot(DayOfWeek.TUESDAY, 14), null);

        assertThatThrownBy(() -> appointmentService.create(req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC10
    @Test
    @DisplayName("create rejects email without @ character")
    void testCreateInvalidEmail() {
        CreateAppointmentRequest req = new CreateAppointmentRequest(
                1L, "John Doe", "invalidexample.com",
                validFutureSlot(DayOfWeek.TUESDAY, 14), null);

        assertThatThrownBy(() -> appointmentService.create(req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC11
    @Test
    @DisplayName("create rejects null start time")
    void testCreateNullStartTime() {
        CreateAppointmentRequest req = new CreateAppointmentRequest(
                1L, "John Doe", "john@example.com", null, null);

        assertThatThrownBy(() -> appointmentService.create(req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC12
    @Test
    @DisplayName("create rejects start time with non-zero seconds or nanos")
    void testCreateWithSeconds() {
        // normalizeStartTime runs before validateTimeWindow, so BAD_REQUEST fires
        // regardless of whether the date is in the past or future.
        LocalDateTime withSeconds = LocalDateTime.of(2026, 9, 1, 14, 0, 30);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));

        CreateAppointmentRequest req = new CreateAppointmentRequest(
                1L, "John Doe", "john@example.com", withSeconds, null);

        assertThatThrownBy(() -> appointmentService.create(req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC13
    @Test
    @DisplayName("create rejects time slot not aligned to 15-minute intervals")
    void testCreateMisalignedSlot() {
        LocalDateTime misaligned = LocalDateTime.of(2026, 9, 1, 14, 5, 0);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));

        CreateAppointmentRequest req = new CreateAppointmentRequest(
                1L, "John Doe", "john@example.com", misaligned, null);

        assertThatThrownBy(() -> appointmentService.create(req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC14
    @Test
    @DisplayName("create rejects appointment with less than 2 hours advance notice")
    void testCreateInsufficientNotice() {
        // slotWithinTwoHours() returns now+[75,90]min → always < 2h, on 15-min boundary
        LocalDateTime tooSoon = slotWithinTwoHours();
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));

        assertThatThrownBy(() -> appointmentService.create(validRequest(tooSoon)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC15
    @Test
    @DisplayName("create rejects appointment more than 90 days in future")
    void testCreateBeyondWindow() {
        // 92 days in the future: exceeds MAX_PLANNING_WINDOW of 90 days
        LocalDateTime farFuture = LocalDate.now().plusDays(92).atTime(10, 0);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));

        assertThatThrownBy(() -> appointmentService.create(validRequest(farFuture)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC17
    @Test
    @DisplayName("create rejects appointment outside business hours (09:00-17:00)")
    void testCreateOutsideHours() {
        // 18:00 → end 18:30 > CLOSE_TIME 17:00; 10 days out passes notice + window guards
        LocalDateTime outside = LocalDate.now().plusDays(10).atTime(18, 0);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));

        assertThatThrownBy(() -> appointmentService.create(validRequest(outside)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC18
    @Test
    @DisplayName("create rejects when customer already has 3 future appointments")
    void testCreateMaxBookingsExceeded() {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of(
                        scheduledAppointment(10L, start.plusDays(1), 30),
                        scheduledAppointment(11L, start.plusDays(2), 30),
                        scheduledAppointment(12L, start.plusDays(3), 30)
                ));

        assertThatThrownBy(() -> appointmentService.create(validRequest(start)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC19
    @Test
    @DisplayName("create rejects same-day booking with less than 2 hours notice")
    void testCreateTodayShortNotice() {
        // validateTimeWindow fires first (before ensureCustomerCanBook same-day check).
        // slotWithinTwoHours() is typically today; always triggers CONFLICT from validateTimeWindow.
        LocalDateTime tooSoon = slotWithinTwoHours();
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));

        assertThatThrownBy(() -> appointmentService.create(validRequest(tooSoon)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC20
    @Test
    @DisplayName("create rejects when requested time conflicts with existing SCHEDULED appointment")
    void testCreateTimeConflict() {
        LocalDate futureDate = LocalDate.now().plusDays(10);
        LocalDateTime existStart = futureDate.atTime(14, 0);
        LocalDateTime existEnd   = futureDate.atTime(14, 30);
        LocalDateTime newStart   = futureDate.atTime(14, 15); // overlaps 14:00-14:30

        Appointment existing = new Appointment(
                1L, "H", "Other", "other@example.com",
                existStart, existEnd, BigDecimal.valueOf(100), null);
        existing.assignId(99L);

        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, BigDecimal.valueOf(100))));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of());
        when(appointmentRepository.findAll()).thenReturn(List.of(existing));

        assertThatThrownBy(() -> appointmentService.create(validRequest(newStart)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC21
    @Test
    @DisplayName("create prices weekday appointment at base price (no multipliers)")
    void testCreateWeekdayPrice() {
        LocalDateTime tuesday14 = validFutureSlot(DayOfWeek.TUESDAY, 14);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, new BigDecimal("100.00"))));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of());
        when(appointmentRepository.findAll()).thenReturn(List.of());
        when(appointmentRepository.save(any())).thenAnswer(inv -> {
            Appointment a = inv.getArgument(0); a.assignId(1L); return a;
        });

        AppointmentResponse result = appointmentService.create(validRequest(tuesday14));

        assertThat(result.price()).isEqualByComparingTo(new BigDecimal("100.00"));
    }

    // TC22
    @Test
    @DisplayName("create applies 1.20x multiplier to weekend appointments")
    void testCreateWeekendPrice() {
        LocalDateTime saturday14 = validFutureSlot(DayOfWeek.SATURDAY, 14);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, new BigDecimal("100.00"))));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of());
        when(appointmentRepository.findAll()).thenReturn(List.of());
        when(appointmentRepository.save(any())).thenAnswer(inv -> {
            Appointment a = inv.getArgument(0); a.assignId(1L); return a;
        });

        AppointmentResponse result = appointmentService.create(validRequest(saturday14));

        assertThat(result.price()).isEqualByComparingTo(new BigDecimal("120.00"));
    }

    // TC23
    @Test
    @DisplayName("create applies 1.15x multiplier for services longer than 45 minutes")
    void testCreateLongServicePrice() {
        // duration=60 > 45 → 1.15x; weekday → no weekend multiplier
        LocalDateTime tuesday10 = validFutureSlot(DayOfWeek.TUESDAY, 10); // end 11:00 ≤ 17:00
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(60, new BigDecimal("100.00"))));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of());
        when(appointmentRepository.findAll()).thenReturn(List.of());
        when(appointmentRepository.save(any())).thenAnswer(inv -> {
            Appointment a = inv.getArgument(0); a.assignId(1L); return a;
        });

        AppointmentResponse result = appointmentService.create(validRequest(tuesday10));

        assertThat(result.price()).isEqualByComparingTo(new BigDecimal("115.00"));
    }

    // TC24
    @Test
    @DisplayName("create combines multipliers: weekend 1.20 × long service 1.15 = 1.38")
    void testCreateCombinedPriceMultipliers() {
        // Sunday + 60 min → 100 × 1.20 × 1.15 = 138.00
        LocalDateTime sunday10 = validFutureSlot(DayOfWeek.SUNDAY, 10);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(60, new BigDecimal("100.00"))));
        when(appointmentRepository.findFutureActiveByCustomer(anyString(), any()))
                .thenReturn(List.of());
        when(appointmentRepository.findAll()).thenReturn(List.of());
        when(appointmentRepository.save(any())).thenAnswer(inv -> {
            Appointment a = inv.getArgument(0); a.assignId(1L); return a;
        });

        AppointmentResponse result = appointmentService.create(validRequest(sunday10));

        assertThat(result.price()).isEqualByComparingTo(new BigDecimal("138.00"));
    }

    // ─────────────────────────────────────────────────────────────────
    // TC25 – TC27 · cancel
    // ─────────────────────────────────────────────────────────────────

    // TC25
    @Test
    @DisplayName("cancel SCHEDULED appointment successfully when 1+ hours before start")
    void testCancelSuccess() {
        // validFutureSlot is ~7+ days away → definitely > 1h from now
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment a = scheduledAppointment(1L, start, 30);
        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));
        when(appointmentRepository.save(any())).thenReturn(a);

        AppointmentResponse result = appointmentService.cancel(1L);

        assertThat(result.status()).isEqualTo(AppointmentStatus.CANCELLED);
    }

    // TC26
    @Test
    @DisplayName("cancel rejects non-SCHEDULED appointments")
    void testCancelNotScheduled() {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment a = scheduledAppointment(1L, start, 30);
        a.cancel(); // status → CANCELLED
        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));

        assertThatThrownBy(() -> appointmentService.cancel(1L))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC27
    @Test
    @DisplayName("cancel rejects when within 1 hour of start time")
    void testCancelTooLate() {
        // slotWithinOneHour() → now+[15,30]min → startTime < now+1h → rejection
        LocalDateTime soonStart = slotWithinOneHour();
        Appointment a = scheduledAppointment(1L, soonStart, 30);
        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));

        assertThatThrownBy(() -> appointmentService.cancel(1L))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // ─────────────────────────────────────────────────────────────────
    // TC28 – TC31 · reschedule
    // ─────────────────────────────────────────────────────────────────

    // TC29
    @Test
    @DisplayName("reschedule rejects null request")
    void testRescheduleNullRequest() {
        assertThatThrownBy(() -> appointmentService.reschedule(1L, null))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.BAD_REQUEST));
    }

    // TC30
    @Test
    @DisplayName("reschedule rejects non-SCHEDULED appointments")
    void testRescheduleNotScheduled() {
        LocalDateTime start = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment a = scheduledAppointment(1L, start, 30);
        a.complete(); // status → COMPLETED
        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));

        RescheduleAppointmentRequest req = new RescheduleAppointmentRequest(
                validFutureSlot(DayOfWeek.WEDNESDAY, 10));

        assertThatThrownBy(() -> appointmentService.reschedule(1L, req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC31
    @Test
    @DisplayName("reschedule rejects when within 1 hour of current start time")
    void testRescheduleAppointmentTooLate() {
        LocalDateTime soonStart = slotWithinOneHour();
        Appointment a = scheduledAppointment(1L, soonStart, 30);
        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));

        RescheduleAppointmentRequest req = new RescheduleAppointmentRequest(
                validFutureSlot(DayOfWeek.WEDNESDAY, 10));

        assertThatThrownBy(() -> appointmentService.reschedule(1L, req))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.CONFLICT));
    }

    // TC28
    @Test
    @DisplayName("reschedule SCHEDULED appointment to new time with recalculated price when 1+ hour notice")
    void testRescheduleSuccess() {
        LocalDateTime existStart = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment a = scheduledAppointment(1L, existStart, 30);

        when(appointmentRepository.findById(1L)).thenReturn(Optional.of(a));
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, new BigDecimal("100.00"))));
        when(appointmentRepository.findAll()).thenReturn(List.of()); // no conflicts
        when(appointmentRepository.save(any())).thenReturn(a);

        LocalDateTime newStart = validFutureSlot(DayOfWeek.WEDNESDAY, 10);
        RescheduleAppointmentRequest req = new RescheduleAppointmentRequest(newStart);

        AppointmentResponse result = appointmentService.reschedule(1L, req);

        assertThat(result.status()).isEqualTo(AppointmentStatus.SCHEDULED);
        assertThat(result.startTime()).isEqualTo(newStart);
    }

    // ─────────────────────────────────────────────────────────────────
    // TC32, TC33, TC37, TC38 · availability
    // ─────────────────────────────────────────────────────────────────

    // TC32
    @Test
    @DisplayName("availability returns list of slots with null reason for available times")
    void testAvailabilityAllOpen() {
        // A future weekday with no existing appointments → all slots available
        LocalDate futureDate = LocalDate.now().plusDays(14)
                .with(TemporalAdjusters.nextOrSame(DayOfWeek.TUESDAY));
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, new BigDecimal("100.00"))));
        when(appointmentRepository.findScheduledOnDate(futureDate)).thenReturn(List.of());

        List<AvailabilitySlotResponse> slots = appointmentService.availability(1L, futureDate);

        assertThat(slots).isNotEmpty();
        assertThat(slots).allMatch(AvailabilitySlotResponse::available);
        assertThat(slots).allMatch(s -> s.reason() == null);
    }

    // TC33
    @Test
    @DisplayName("availability marks past time slots with reason: 'termin juz minąl'")
    void testAvailabilityPastSlots() {
        // Yesterday → every generated slot is before LocalDateTime.now() → "termin juz minąl"
        LocalDate yesterday = LocalDate.now().minusDays(1);
        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, new BigDecimal("100.00"))));
        when(appointmentRepository.findScheduledOnDate(yesterday)).thenReturn(List.of());

        List<AvailabilitySlotResponse> slots = appointmentService.availability(1L, yesterday);

        assertThat(slots).isNotEmpty();
        assertThat(slots).allMatch(s -> "termin juz minąl".equals(s.reason()));
        assertThat(slots).allMatch(s -> !s.available());
    }

    // TC37
    @Test
    @DisplayName("availability marks slots with existing appointment conflicts with reason: 'termin zajety'")
    void testAvailabilityConflictedSlots() {
        LocalDate futureDate = LocalDate.now().plusDays(14)
                .with(TemporalAdjusters.nextOrSame(DayOfWeek.TUESDAY));

        // Existing 14:00-14:30; the 14:15 slot overlaps it
        LocalDateTime existStart = futureDate.atTime(14, 0);
        LocalDateTime existEnd   = futureDate.atTime(14, 30);
        Appointment existing = new Appointment(
                1L, "H", "Other", "other@example.com",
                existStart, existEnd, BigDecimal.valueOf(100), null);
        existing.assignId(99L);

        when(serviceOfferRepository.findById(1L))
                .thenReturn(Optional.of(activeOffer(30, new BigDecimal("100.00"))));
        when(appointmentRepository.findScheduledOnDate(futureDate)).thenReturn(List.of(existing));

        List<AvailabilitySlotResponse> slots = appointmentService.availability(1L, futureDate);

        assertThat(slots).anySatisfy(s -> {
            assertThat(s.startTime()).isEqualTo(futureDate.atTime(14, 15));
            assertThat(s.reason()).isEqualTo("termin zajety");
            assertThat(s.available()).isFalse();
        });
    }

    // TC38
    @Test
    @DisplayName("availability throws NOT_FOUND when service is inactive (getActiveServiceOfferOrThrow rejects before slots are generated)")
    void testAvailabilityInactiveService() {
        // NOTE: plan describes reason 'usluga nieaktywna' in slot list, but the code
        // throws ApiException(NOT_FOUND) from getActiveServiceOfferOrThrow() before
        // any slots are generated. availabilityReason()'s offer.isActive() branch is
        // unreachable from availability(). This test characterises the actual behaviour.
        ServiceOffer inactive = new ServiceOffer("Inactive", 30, BigDecimal.valueOf(100), false);
        inactive.assignId(1L);
        when(serviceOfferRepository.findById(1L)).thenReturn(Optional.of(inactive));

        assertThatThrownBy(() -> appointmentService.availability(1L, LocalDate.now().plusDays(5)))
                .isInstanceOf(ApiException.class)
                .satisfies(ex -> assertThat(((ApiException) ex).getStatus())
                        .isEqualTo(HttpStatus.NOT_FOUND));
    }

    // ─────────────────────────────────────────────────────────────────
    // TC39 – TC44 · dashboard
    // ─────────────────────────────────────────────────────────────────

    // TC39
    @Test
    @DisplayName("dashboard returns zero counts when repository is empty")
    void testDashboardEmpty() {
        when(appointmentRepository.findAll()).thenReturn(List.of());
        when(appointmentRepository.findUpcoming(any())).thenReturn(List.of());
        when(serviceOfferRepository.findAll()).thenReturn(List.of());

        DashboardResponse result = appointmentService.dashboard();

        assertThat(result.totalAppointments()).isZero();
        assertThat(result.projectedRevenue()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(result.realizedRevenue()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(result.nextAppointmentStart()).isNull();
    }

    // TC40
    @Test
    @DisplayName("dashboard counts appointments grouped by status in returned map")
    void testDashboardStatusCounts() {
        LocalDateTime future = validFutureSlot(DayOfWeek.TUESDAY, 14);
        List<Appointment> all = new ArrayList<>();

        for (int i = 0; i < 5; i++) {
            all.add(scheduledAppointment(i + 1L, future.plusHours(i), 30));
        }
        Appointment c1 = scheduledAppointment(10L, future.plusHours(5), 30); c1.cancel();
        Appointment c2 = scheduledAppointment(11L, future.plusHours(6), 30); c2.cancel();
        all.add(c1); all.add(c2);

        LocalDateTime past = LocalDateTime.now().minusDays(3).withHour(14).withMinute(0)
                .withSecond(0).withNano(0);
        Appointment cp1 = scheduledAppointment(20L, past, 30); cp1.complete();
        Appointment cp2 = scheduledAppointment(21L, past.plusHours(1), 30); cp2.complete();
        Appointment cp3 = scheduledAppointment(22L, past.plusHours(2), 30); cp3.complete();
        all.add(cp1); all.add(cp2); all.add(cp3);

        when(appointmentRepository.findAll()).thenReturn(all);
        when(appointmentRepository.findUpcoming(any())).thenReturn(List.of());
        when(serviceOfferRepository.findAll()).thenReturn(List.of());

        DashboardResponse result = appointmentService.dashboard();

        assertThat(result.countsByStatus().get(AppointmentStatus.SCHEDULED)).isEqualTo(5L);
        assertThat(result.countsByStatus().get(AppointmentStatus.CANCELLED)).isEqualTo(2L);
        assertThat(result.countsByStatus().get(AppointmentStatus.COMPLETED)).isEqualTo(3L);
    }

    // TC41
    @Test
    @DisplayName("dashboard calculates projected revenue from future SCHEDULED appointments only")
    void testDashboardProjectedRevenue() {
        LocalDateTime future = validFutureSlot(DayOfWeek.TUESDAY, 14);
        Appointment a1 = new Appointment(1L, "H", "A", "a@a.com",
                future, future.plusMinutes(30), new BigDecimal("100.00"), null);
        a1.assignId(1L);
        Appointment a2 = new Appointment(1L, "H", "B", "b@b.com",
                future.plusHours(1), future.plusHours(1).plusMinutes(30),
                new BigDecimal("150.00"), null);
        a2.assignId(2L);

        when(appointmentRepository.findAll()).thenReturn(List.of(a1, a2));
        when(appointmentRepository.findUpcoming(any())).thenReturn(List.of());
        when(serviceOfferRepository.findAll()).thenReturn(List.of());

        DashboardResponse result = appointmentService.dashboard();

        assertThat(result.projectedRevenue()).isEqualByComparingTo(new BigDecimal("250.00"));
    }

    // TC42
    @Test
    @DisplayName("dashboard sums realized revenue from COMPLETED appointments")
    void testDashboardRealizedRevenue() {
        LocalDateTime past = LocalDateTime.now().minusDays(2)
                .withHour(14).withMinute(0).withSecond(0).withNano(0);
        Appointment cp1 = new Appointment(1L, "H", "A", "a@a.com",
                past, past.plusMinutes(30), new BigDecimal("70.00"), null);
        cp1.assignId(1L); cp1.complete();
        Appointment cp2 = new Appointment(1L, "H", "B", "b@b.com",
                past.plusHours(1), past.plusHours(1).plusMinutes(30),
                new BigDecimal("80.00"), null);
        cp2.assignId(2L); cp2.complete();
        Appointment cp3 = new Appointment(1L, "H", "C", "c@c.com",
                past.plusHours(2), past.plusHours(2).plusMinutes(30),
                new BigDecimal("70.00"), null);
        cp3.assignId(3L); cp3.complete();

        when(appointmentRepository.findAll()).thenReturn(List.of(cp1, cp2, cp3));
        when(appointmentRepository.findUpcoming(any())).thenReturn(List.of());
        when(serviceOfferRepository.findAll()).thenReturn(List.of());

        DashboardResponse result = appointmentService.dashboard();

        assertThat(result.realizedRevenue()).isEqualByComparingTo(new BigDecimal("220.00"));
    }

    // TC43
    @Test
    @DisplayName("dashboard returns first chronological upcoming scheduled appointment start time")
    void testDashboardNextAppointment() {
        LocalDateTime t1 = validFutureSlot(DayOfWeek.TUESDAY, 14);
        LocalDateTime t2 = t1.plusHours(1);
        LocalDateTime t3 = t1.plusHours(2);
        Appointment a1 = scheduledAppointment(1L, t1, 30);
        Appointment a2 = scheduledAppointment(2L, t2, 30);
        Appointment a3 = scheduledAppointment(3L, t3, 30);

        when(appointmentRepository.findAll()).thenReturn(List.of(a1, a2, a3));
        // findUpcoming returns sorted list; findFirst() picks the earliest
        when(appointmentRepository.findUpcoming(any())).thenReturn(List.of(a1, a2, a3));
        when(serviceOfferRepository.findAll()).thenReturn(List.of());

        DashboardResponse result = appointmentService.dashboard();

        assertThat(result.nextAppointmentStart()).isEqualTo(t1);
    }

    // TC44
//    @Test
//    @DisplayName("dashboard skips null prices when summing revenue")
//    void testDashboardNullPrices() {
//        // Appointment constructor forbids null price via Objects.requireNonNull.
//        // Mockito mocks are used here as the only way to present null-priced objects
//        // to the sum() method without modifying production code.
//        LocalDateTime future = validFutureSlot(DayOfWeek.TUESDAY, 14);
//
//        Appointment a1 = mock(Appointment.class);
//        when(a1.getStatus()).thenReturn(AppointmentStatus.COMPLETED);
//        when(a1.getPrice()).thenReturn(new BigDecimal("100.00"));
//        when(a1.getStartTime()).thenReturn(future);
//
//        Appointment a2 = mock(Appointment.class);
//        when(a2.getStatus()).thenReturn(AppointmentStatus.COMPLETED);
//        when(a2.getPrice()).thenReturn(null); // null price — must be skipped by sum()
//        when(a2.getStartTime()).thenReturn(future.plusHours(1));
//
//        Appointment a3 = mock(Appointment.class);
//        when(a3.getStatus()).thenReturn(AppointmentStatus.COMPLETED);
//        when(a3.getPrice()).thenReturn(new BigDecimal("50.00"));
//        when(a3.getStartTime()).thenReturn(future.plusHours(2));
//
//        when(appointmentRepository.findAll()).thenReturn(List.of(a1, a2, a3));
//        when(appointmentRepository.findUpcoming(any())).thenReturn(List.of());
//        when(serviceOfferRepository.findAll()).thenReturn(List.of());
//
//        DashboardResponse result = appointmentService.dashboard();
//
//        // 100 + null (skipped) + 50 = 150
//        assertThat(result.realizedRevenue()).isEqualByComparingTo(new BigDecimal("150.00"));
//    }
}

