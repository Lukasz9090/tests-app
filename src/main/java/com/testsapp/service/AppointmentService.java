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
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.DayOfWeek;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
@Service
public class AppointmentService {
    private static final LocalTime OPEN_TIME = LocalTime.of(9, 0);
    private static final LocalTime CLOSE_TIME = LocalTime.of(17, 0);
    private static final int SLOT_STEP_MINUTES = 15;
    private static final int MAX_FUTURE_APPOINTMENTS_PER_CUSTOMER = 3;
    private static final Duration MINIMUM_NOTICE = Duration.ofHours(2);
    private static final Duration MAX_PLANNING_WINDOW = Duration.ofDays(90);
    private final AppointmentRepository appointmentRepository;
    private final ServiceOfferRepository serviceOfferRepository;
    private final NotificationService notificationService;
    public AppointmentService(
            AppointmentRepository appointmentRepository,
            ServiceOfferRepository serviceOfferRepository,
            NotificationService notificationService
    ) {
        this.appointmentRepository = appointmentRepository;
        this.serviceOfferRepository = serviceOfferRepository;
        this.notificationService = notificationService;
    }
    public List<AppointmentResponse> listAppointments(String customerEmail, AppointmentStatus status) {
        List<Appointment> appointments = appointmentRepository.findAll();
        return appointments.stream()
                .filter(item -> customerEmail == null || customerEmail.isBlank() || item.getCustomerEmail().equalsIgnoreCase(customerEmail.trim()))
                .filter(item -> status == null || item.getStatus() == status)
                .map(this::toResponse)
                .toList();
    }
    public AppointmentResponse getById(long id) {
        return toResponse(getAppointmentOrThrow(id));
    }
    public AppointmentResponse create(CreateAppointmentRequest request) {
        validateCreateRequest(request);
        ServiceOffer offer = getActiveServiceOfferOrThrow(request.serviceOfferId());
        LocalDateTime startTime = normalizeStartTime(request.startTime());
        LocalDateTime endTime = startTime.plusMinutes(offer.getDurationMinutes());
        validateTimeWindow(startTime, endTime);
        ensureCustomerCanBook(request.customerEmail(), startTime);
        ensureSlotIsFree(startTime, endTime, -1L);
        BigDecimal price = calculatePrice(offer, startTime);
        Appointment appointment = new Appointment(
                offer.getId(),
                offer.getName(),
                normalizeText(request.customerName()),
                normalizeText(request.customerEmail()),
                startTime,
                endTime,
                price,
                request.notes()
        );
        Appointment saved = appointmentRepository.save(appointment);
        notificationService.sendAppointmentCreatedNotification(saved);
        return toResponse(saved);
    }
    public AppointmentResponse cancel(long id) {
        Appointment appointment = getAppointmentOrThrow(id);
        if (appointment.getStatus() != AppointmentStatus.SCHEDULED) {
            throw new ApiException(HttpStatus.CONFLICT, "Tylko zaplanowana wizyte mozna anulowac.");
        }
        if (appointment.getStartTime().isBefore(LocalDateTime.now().plusHours(1))) {
            throw new ApiException(HttpStatus.CONFLICT, "Nie mozna anulowac wizyty pozniej niz godzine przed terminem.");
        }
        appointment.cancel();
        appointmentRepository.save(appointment);
        notificationService.sendAppointmentCancelledNotification(appointment);
        return toResponse(appointment);
    }
    public AppointmentResponse reschedule(long id, RescheduleAppointmentRequest request) {
        if (request == null || request.newStartTime() == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Nowy termin jest wymagany.");
        }
        Appointment appointment = getAppointmentOrThrow(id);
        if (appointment.getStatus() != AppointmentStatus.SCHEDULED) {
            throw new ApiException(HttpStatus.CONFLICT, "Mozna przelozyc tylko zaplanowana wizyte.");
        }
        if (appointment.getStartTime().isBefore(LocalDateTime.now().plusHours(1))) {
            throw new ApiException(HttpStatus.CONFLICT, "Wizyty bliskiej terminu nie mozna przelozyc.");
        }
        ServiceOffer offer = getActiveServiceOfferOrThrow(appointment.getServiceOfferId());
        LocalDateTime previousStartTime = appointment.getStartTime();
        LocalDateTime newStart = normalizeStartTime(request.newStartTime());
        LocalDateTime newEnd = newStart.plusMinutes(offer.getDurationMinutes());
        validateTimeWindow(newStart, newEnd);
        ensureSlotIsFree(newStart, newEnd, appointment.getId());
        BigDecimal newPrice = calculatePrice(offer, newStart);
        appointment.reschedule(newStart, newEnd, newPrice);
        appointmentRepository.save(appointment);
        notificationService.sendAppointmentRescheduledNotification(appointment, previousStartTime);
        return toResponse(appointment);
    }
    public List<AvailabilitySlotResponse> availability(long serviceOfferId, LocalDate date) {
        ServiceOffer offer = getActiveServiceOfferOrThrow(serviceOfferId);
        LocalDate targetDate = date == null ? LocalDate.now() : date;
        LocalDateTime cursor = targetDate.atTime(OPEN_TIME);
        LocalDateTime closeBoundary = targetDate.atTime(CLOSE_TIME);
        List<Appointment> scheduled = appointmentRepository.findScheduledOnDate(targetDate);
        List<AvailabilitySlotResponse> slots = new ArrayList<>();
        while (!cursor.plusMinutes(offer.getDurationMinutes()).isAfter(closeBoundary)) {
            LocalDateTime end = cursor.plusMinutes(offer.getDurationMinutes());
            String reason = availabilityReason(cursor, end, scheduled, offer);
            slots.add(new AvailabilitySlotResponse(cursor, end, reason == null, reason));
            cursor = cursor.plusMinutes(SLOT_STEP_MINUTES);
        }
        return slots;
    }
    public DashboardResponse dashboard() {
        LocalDateTime now = LocalDateTime.now();
        List<Appointment> all = appointmentRepository.findAll();
        Map<AppointmentStatus, Long> counts = new EnumMap<>(AppointmentStatus.class);
        for (AppointmentStatus status : AppointmentStatus.values()) {
            counts.put(status, all.stream().filter(item -> item.getStatus() == status).count());
        }
        BigDecimal projectedRevenue = sum(all.stream()
                .filter(item -> item.getStatus() == AppointmentStatus.SCHEDULED && item.getStartTime().isAfter(now))
                .map(Appointment::getPrice)
                .toList());
        BigDecimal realizedRevenue = sum(all.stream()
                .filter(item -> item.getStatus() == AppointmentStatus.COMPLETED)
                .map(Appointment::getPrice)
                .toList());
        LocalDateTime nextAppointment = appointmentRepository.findUpcoming(now).stream()
                .findFirst()
                .map(Appointment::getStartTime)
                .orElse(null);
        return new DashboardResponse(
                serviceOfferRepository.findAll().size(),
                all.size(),
                counts,
                projectedRevenue,
                realizedRevenue,
                nextAppointment
        );
    }
    private Appointment getAppointmentOrThrow(long id) {
        return appointmentRepository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono wizyty o id=" + id));
    }
    private ServiceOffer getActiveServiceOfferOrThrow(long id) {
        return serviceOfferRepository.findById(id)
                .filter(ServiceOffer::isActive)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono aktywnej uslugi o id=" + id));
    }
    private void validateCreateRequest(CreateAppointmentRequest request) {
        if (request == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Brak danych wizyty.");
        }
        if (request.customerName() == null || request.customerName().isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Imie i nazwisko klienta jest wymagane.");
        }
        if (request.customerEmail() == null || request.customerEmail().isBlank() || !request.customerEmail().contains("@")) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Poprawny e-mail klienta jest wymagany.");
        }
        if (request.startTime() == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Termin wizyty jest wymagany.");
        }
    }
    private LocalDateTime normalizeStartTime(LocalDateTime requestedStart) {
        if (requestedStart.getSecond() != 0 || requestedStart.getNano() != 0) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Termin musi byc podany z dokladnoscia do minut.");
        }
        if (requestedStart.getMinute() % SLOT_STEP_MINUTES != 0) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Termin musi zaczynac sie co 15 minut.");
        }
        return requestedStart;
    }
    private void validateTimeWindow(LocalDateTime startTime, LocalDateTime endTime) {
        LocalDateTime now = LocalDateTime.now();
        if (startTime.isBefore(now.plus(MINIMUM_NOTICE))) {
            throw new ApiException(HttpStatus.CONFLICT, "Rezerwacja wymaga co najmniej 2 godzin wyprzedzenia.");
        }
        if (startTime.isAfter(now.plus(MAX_PLANNING_WINDOW))) {
            throw new ApiException(HttpStatus.CONFLICT, "Wizyte mozna zaplanowac maksymalnie 90 dni do przodu.");
        }
        if (startTime.toLocalDate().isAfter(endTime.toLocalDate())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Wizyta nie moze przechodzic na kolejny dzien.");
        }
        if (startTime.toLocalTime().isBefore(OPEN_TIME) || endTime.toLocalTime().isAfter(CLOSE_TIME)) {
            throw new ApiException(HttpStatus.CONFLICT, "Wizyta musi miescic sie w godzinach 09:00-17:00.");
        }
    }
    private void ensureCustomerCanBook(String customerEmail, LocalDateTime startTime) {
        int futureCount = appointmentRepository.findFutureActiveByCustomer(customerEmail, LocalDateTime.now()).size();
        if (futureCount >= MAX_FUTURE_APPOINTMENTS_PER_CUSTOMER) {
            throw new ApiException(HttpStatus.CONFLICT, "Klient ma juz maksymalna liczbe przyszlych wizyt.");
        }
        if (startTime.toLocalDate().equals(LocalDate.now()) && startTime.isBefore(LocalDateTime.now().plusHours(2))) {
            throw new ApiException(HttpStatus.CONFLICT, "Wizyty na dzis wymagaja wiekszego wyprzedzenia.");
        }
    }
    private void ensureSlotIsFree(LocalDateTime start, LocalDateTime end, long excludedAppointmentId) {
        boolean conflict = appointmentRepository.findAll().stream()
                .filter(item -> item.getStatus() == AppointmentStatus.SCHEDULED)
                .filter(item -> item.getId() != excludedAppointmentId)
                .anyMatch(item -> overlaps(start, end, item.getStartTime(), item.getEndTime()));
        if (conflict) {
            throw new ApiException(HttpStatus.CONFLICT, "Wybrany termin jest juz zajety.");
        }
    }
    private boolean overlaps(LocalDateTime start1, LocalDateTime end1, LocalDateTime start2, LocalDateTime end2) {
        return start1.isBefore(end2) && end1.isAfter(start2);
    }
    private String availabilityReason(LocalDateTime start, LocalDateTime end, List<Appointment> scheduled, ServiceOffer offer) {
        LocalDateTime now = LocalDateTime.now();
        if (start.isBefore(now)) {
            return "termin juz minąl";
        }
        if (start.isBefore(now.plus(MINIMUM_NOTICE))) {
            return "za malo czasu na rezerwacje";
        }
        if (start.toLocalDate().equals(LocalDate.now()) && start.isBefore(now.plusHours(2))) {
            return "za malo czasu na rezerwacje dzisiejsza";
        }
        if (start.toLocalTime().isBefore(OPEN_TIME) || end.toLocalTime().isAfter(CLOSE_TIME)) {
            return "poza godzinami pracy";
        }
        boolean conflict = scheduled.stream().anyMatch(item -> overlaps(start, end, item.getStartTime(), item.getEndTime()));
        if (conflict) {
            return "termin zajety";
        }
        if (!offer.isActive()) {
            return "usluga nieaktywna";
        }
        return null;
    }
    private BigDecimal calculatePrice(ServiceOffer offer, LocalDateTime startTime) {
        BigDecimal price = offer.getBasePrice();
        if (isWeekend(startTime)) {
            price = price.multiply(BigDecimal.valueOf(1.20));
        }
        if (offer.getDurationMinutes() > 45) {
            price = price.multiply(BigDecimal.valueOf(1.15));
        }
        return price.setScale(2, RoundingMode.HALF_UP);
    }
    private boolean isWeekend(LocalDateTime dateTime) {
        DayOfWeek dayOfWeek = dateTime.getDayOfWeek();
        return dayOfWeek == DayOfWeek.SATURDAY || dayOfWeek == DayOfWeek.SUNDAY;
    }
    private BigDecimal sum(List<BigDecimal> values) {
        BigDecimal total = BigDecimal.ZERO;
        for (BigDecimal value : values) {
            if (value != null) {
                total = total.add(value);
            }
        }
        return total.setScale(2, RoundingMode.HALF_UP);
    }
    private String normalizeText(String value) {
        return value == null ? "" : value.trim();
    }
    private AppointmentResponse toResponse(Appointment appointment) {
        return new AppointmentResponse(
                appointment.getId(),
                appointment.getServiceOfferId(),
                appointment.getServiceName(),
                appointment.getCustomerName(),
                appointment.getCustomerEmail(),
                appointment.getStartTime(),
                appointment.getEndTime(),
                appointment.getStatus(),
                appointment.getPrice(),
                appointment.getNotes(),
                appointment.getCreatedAt(),
                appointment.getUpdatedAt()
        );
    }
}
